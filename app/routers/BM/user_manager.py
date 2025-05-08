from fastapi import Depends, HTTPException, status, APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from starlette.responses import JSONResponse

from app.db_services.database import get_db
from app.logger import get_logger
from app.models import User
from app.schemas.user_schema import UserResponse, UserCreate, UserTypeUpdate, UserLogin
from app.services.user_service import create_user_service, delete_user_service, verify_user_login

router = APIRouter()
logger = get_logger('user_router')


# 登录接口
@router.post("/login")
async def login_for_access_token(login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    user, token = await verify_user_login(db, login_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"access_token": token, "token_type": "bearer"}


# 登出接口
@router.post("/logout")
async def logout():
    """用户登出"""
    # 客户端收到响应后主动删除本地存储的JWT
    return {"message": "Logged out successfully"}


# 查询所有用户接口
@router.get("/all")
async def get_all_users(db: AsyncSession = Depends(get_db)):
    """获取所有用户"""
    result = await db.execute(select(User))
    return result.scalars().all()


# 后台操作 新增用户
@router.post("/create", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """新增用户"""
    try:
        user, token = await create_user_service(db, user_data)
        logger.info(f"用户创建成功: {user.model_dump()}")
        return {
            "user": user.model_dump(),
            "token": token
        }
    except HTTPException as e:
        logger.error(f"用户创建失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"用户创建失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "创建用户失败",
                "errors": [str(e)]
            }
        )


# 跟新用户角色权限
@router.patch("/user_type/{user_id}")
async def update_user_type(
        user_id: int,
        user_update: UserTypeUpdate,
        db: AsyncSession = Depends(get_db)
):
    """仅更新用户类型字段"""
    try:
        # 获取用户
        result = await db.execute(select(User).where(User.id == user_id))
        db_user = result.scalars().first()
        if not db_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 仅更新user_type字段
        if user_update.user_type is not None:
            print(".....................", user_update.user_type)
            db_user.user_type = user_update.user_type

        await db.commit()
        await db.refresh(db_user)

        return JSONResponse(content={"message": "操作成功"}, status_code=200)
    except Exception as e:
        logger.error(f"用户更新失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "更新用户信息失败",
                "errors": [str(e)]
            }
        )


# 删除用户
@router.delete("/delete/{user_id}")
async def delete_user(
        user_id: int,
        db: AsyncSession = Depends(get_db)
):
    """删除用户"""
    try:
        # 查找用户
        result = await db.execute(select(User).where(User.id == user_id))
        db_user = result.scalars().first()

        if not db_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 删除用户
        await db.delete(db_user)
        await db.commit()

        logger.info(f"成功删除用户，用户ID: {user_id}")
        return {"message": "用户删除成功"}

    except HTTPException as e:
        logger.error(f"删除用户失败 - HTTP异常: {str(e)}")
        raise e

    except Exception as e:
        logger.error(f"删除用户失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "删除用户失败",
                "errors": [str(e)]
            }
        )
