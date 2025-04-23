from fastapi import Depends, HTTPException, status, APIRouter
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from datetime import timedelta

from app.config import settings
from app.db_services.database import get_db
from app.dependencies.BM_auth import authenticate_user
from app.logger import get_logger
from app.models import User
from app.utils.jwt import create_access_token

router = APIRouter(prefix="/users")
logger = get_logger('user_router')


# 登录接口
@router.post("/login")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"admin": user.name}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


# 登出接口
@router.post("/logout")
async def logout():
    # 客户端收到响应后主动删除本地存储的JWT
    return {"message": "Logged out successfully"}


# 查询所有用户接口
@router.get("/all")
async def get_all_users(db: AsyncSession = Depends(get_db)):
    """获取所有用户"""
    result = await db.execute(select(User))
    return result.scalars().all()