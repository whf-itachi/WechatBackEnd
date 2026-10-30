from fastapi import Depends, HTTPException, status, APIRouter
from app.utils.enveloping_route import EnvelopingRoute
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from starlette.responses import JSONResponse

from datetime import datetime, timezone

from app.db_services.database import get_db
from app.dependencies.BM_auth import bm_verify_token
from app.logger import get_logger
from app.models import User
from app.schemas.user_schema import (
    UserResponse,
    UserPublic,
    UserCreate,
    UserTypeUpdate,
    UserLogin,
    UserPasswordReset,
)
from app.services.user_service import create_user_service, verify_user_login, get_password_hash

router = APIRouter(route_class=EnvelopingRoute)
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

    return {"access_token": token, "token_type": "bearer", "user_id":user.id, "username":user.name}


# 登出接口
@router.post("/logout")
async def logout():
    """用户登出"""
    # 客户端收到响应后主动删除本地存储的JWT
    return {"message": "Logged out successfully"}

# 注册用户
@router.post("/register", response_model=UserResponse)
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    logger.info(f"收到用户注册请求: {user_data.model_dump(exclude={'password'})}")
    try:
        user, token = await create_user_service(db, user_data)
        logger.info(f"用户注册成功: {UserPublic.model_validate(user).model_dump()}")
        return {
            "user": UserPublic.model_validate(user),
            "token": token
        }
    except HTTPException as e:
        logger.error(f"用户注册失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"用户注册失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "注册失败",
                "errors": [str(e)]
            }
        )



# 查询所有用户接口
@router.get("/all", response_model=list[UserPublic])
async def get_all_users(db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    """获取所有用户（不含已软删除/停用的账号）"""
    result = await db.execute(select(User).where(User.is_active == True))  # noqa: E712
    return result.scalars().all()


# 后台操作 新增用户
@router.post("/create", response_model=UserResponse)
async def create_user_endpoint(user_data: UserCreate, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    """新增用户"""
    try:
        user, token = await create_user_service(db, user_data)
        logger.info(f"用户创建成功: {UserPublic.model_validate(user).model_dump()}")
        return {
            "user": UserPublic.model_validate(user),
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
        db: AsyncSession = Depends(get_db),
        token_payload: dict = Depends(bm_verify_token)
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


# 重置用户登录密码（管理员）
@router.put("/password/{user_id}")
async def reset_user_password(
        user_id: int,
        payload: UserPasswordReset,
        db: AsyncSession = Depends(get_db),
        token_payload: dict = Depends(bm_verify_token)
):
    """管理员重置用户登录密码

    - 只改 password 一个字段，不碰姓名/手机号/邮箱/角色；
    - 不校验旧密码（凭管理员权限），操作人记入日志；
    - 入库前 bcrypt 加密；JWT 中不含密码版本号，重置后该用户已登录的会话
      在 token 过期前仍然有效，如需强制下线要另行处理。
    """
    # 校验新密码：非空 + 长度。bcrypt 只处理前 72 字节，超了会被静默截断，
    # 这里按字节数卡住，避免"密码后半段其实没生效"的隐性问题。
    pwd = (payload.new_password or "").strip()
    if not pwd:
        raise HTTPException(status_code=400, detail="新密码不能为空")
    if len(pwd) < 6 or len(pwd) > 64:
        raise HTTPException(status_code=400, detail="新密码长度需为 6-64 位")
    if len(pwd.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="新密码过长，请控制在 72 字节以内（中文按 3 字节计算）")

    result = await db.execute(select(User).where(User.id == user_id))
    db_user = result.scalars().first()
    if not db_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        db_user.password = get_password_hash(pwd)
        db_user.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(db_user)
    except Exception as e:
        await db.rollback()
        logger.error(f"重置用户密码失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "重置密码失败",
                "errors": [str(e)]
            }
        )

    logger.info(
        f"管理员 {token_payload.get('user_id')} 重置了用户密码，"
        f"目标用户ID: {user_id}, 姓名: {db_user.name}, 账号状态: {'启用' if db_user.is_active else '已停用'}"
    )
    return {
        "user_id": db_user.id,
        "user_name": db_user.name,
        "message": "密码已重置，请通知该用户使用新密码登录"
    }


# 删除用户（软删除：只置 is_active=False，不动 data，保留历史关联数据）
@router.delete("/delete/{user_id}")
async def delete_user(
        user_id: int,
        db: AsyncSession = Depends(get_db),
        token_payload: dict = Depends(bm_verify_token)
):
    """删除用户 —— 软删除

    不物理删除 `user` 行，只把 is_active 置为 False：
    1. 出差记录等业务表通过 user_id 关联，物理删除会连带（CASCADE）抹掉历史账目；
    2. 软删除后登录被拦截（verify_user_login 校验 is_active），并且鉴权依赖也会拒绝其旧 token。
    """
    try:
        # 不允许删除自己，避免把自己锁在系统外
        if str(token_payload.get("user_id")) == str(user_id):
            raise HTTPException(status_code=400, detail="不能删除当前登录的账号")

        # 查找用户
        result = await db.execute(select(User).where(User.id == user_id))
        db_user = result.scalars().first()

        if not db_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if not db_user.is_active:
            return {"message": "该用户已处于停用状态"}

        # 软删除：保留数据，仅停用
        db_user.is_active = False
        await db.commit()

        logger.info(f"成功停用用户（软删除），用户ID: {user_id}, 姓名: {db_user.name}")
        return {"message": "用户已删除（停用），历史数据保留"}

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
