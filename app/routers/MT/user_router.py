from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db_services.database import get_db
from app.services.user_service import (
    create_user_service,
    get_users_service,
    get_user_service,
    update_user_service,
    delete_user_service,
    verify_user_login
)
from app.schemas.user_schema import UserCreate, UserResponse, UserUpdate, UserLogin
from app.dependencies.auth import get_current_user
from app.models.user import User
from typing import List
from app.logger import get_logger

router = APIRouter()
logger = get_logger('user_router')

# 注册用户
@router.post("/register", response_model=UserResponse)
async def register_user(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    logger.info(f"收到用户注册请求: {user_data.model_dump()}")
    try:
        user, token = await create_user_service(db, user_data)
        logger.info(f"用户注册成功: {user.model_dump()}")
        return {
            "user": user.model_dump(),
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

# 用户登录
@router.post("/login", response_model=UserResponse)
async def login_user(login_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    logger.info(f"收到用户登录请求: {login_data.model_dump()}")
    try:
        user, token = await verify_user_login(db, login_data)
        logger.info(f"用户登录成功: {user.model_dump()}")
        return {
            "user": user.model_dump(),
            "token": token
        }
    except HTTPException as e:
        logger.error(f"用户登录失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"用户登录失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "登录失败",
                "errors": [str(e)]
            }
        )

# 获取所有用户列表
@router.get("/", response_model=List[UserResponse])
async def get_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取所有用户列表"""
    logger.info(f"收到获取用户列表请求，当前用户: {current_user.id}")
    try:
        users = await get_users_service(db)
        logger.info(f"成功获取用户列表，共 {len(users)} 条记录")
        return [{"user": user.model_dump()} for user in users]
    except HTTPException as e:
        logger.error(f"获取用户列表失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取用户列表失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "获取用户列表失败",
                "errors": [str(e)]
            }
        )

# 根据ID获取用户信息
@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据ID获取用户信息"""
    logger.info(f"收到获取用户信息请求，用户ID: {user_id}，当前用户: {current_user.id}")
    try:
        user = await get_user_service(db, user_id)
        logger.info(f"成功获取用户信息: {user.model_dump()}")
        return {"user": user.model_dump()}
    except HTTPException as e:
        logger.error(f"获取用户信息失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取用户信息失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "获取用户信息失败",
                "errors": [str(e)]
            }
        )

# 更新用户信息
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新用户信息"""
    logger.info(f"收到更新用户信息请求，用户ID: {user_id}，当前用户: {current_user.id}")
    try:
        user = await update_user_service(db, user_id, user_data)
        logger.info(f"成功更新用户信息: {user.model_dump()}")
        return {"user": user.model_dump()}
    except HTTPException as e:
        logger.error(f"更新用户信息失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"更新用户信息失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "更新用户信息失败",
                "errors": [str(e)]
            }
        )

# 删除用户
@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除用户"""
    logger.info(f"收到删除用户请求，用户ID: {user_id}，当前用户: {current_user.id}")
    try:
        await delete_user_service(db, user_id)
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
