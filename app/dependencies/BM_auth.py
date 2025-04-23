from fastapi import HTTPException, Request, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from passlib.context import CryptContext
from sqlalchemy import select
from starlette import status

from app.db_services.database import AsyncSessionDep
from app.logger import get_logger
from app.models import User
from app.utils.jwt import verify_token


# OAuth2 方案
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

logger = get_logger('user_router')

async def bm_verify_token(request: Request):
    try:
        path = request.url.path
        if path.endswith('/login'):
            pass
        else:
            authorization = request.headers.get("Authorization")
            if not authorization:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未提供认证信息"
                )
            payload = verify_token(authorization)
            if payload:
                raise HTTPException(status_code=400, detail="Token header invalid")
    except Exception as e:
        logger.error("error: ", e)

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 验证密码
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


# 获取用户
async def get_user(session: AsyncSessionDep, username: str):
    logger.info(f"username: {username}")
    result = await session.execute(select(User).where(User.name == username))

    user_info = result.scalars().first()
    return user_info


# 认证用户，校验用户名密码
async def authenticate_user(session: AsyncSessionDep, username: str, password: str):
    user = await get_user(session, username)
    logger.info(user)
    if not user:
        return False
    if not verify_password(password, user.password):
        return False
    return user


# 获取当前用户信息
async def get_current_user(session: AsyncSessionDep, token: str = Depends(oauth2_scheme)):
    try:
        payload = verify_token(token)
        username: str = payload.get("admin")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = get_user(session, username)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )