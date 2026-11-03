from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.jwt import verify_token
from app.db_services.database import get_db
from app.models.user import User
from sqlalchemy import select

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/users/login")

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """获取当前用户"""
    payload = verify_token(token)
    user_id: int = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "无效的认证令牌",
                "errors": ["无法获取用户ID"]
            }
        )
    
    # 从数据库获取用户对象
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "用户不存在",
                "errors": ["用户已被删除或禁用"]
            }
        )

    # 软删除 / 停用后，手里的旧 token 也必须立即失效（否则能一直调到过期）
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "账号已被停用",
                "errors": ["该账号已停用，请联系管理员"]
            }
        )

    return user


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """要求当前登录用户是管理员（user_type == "admin"）

    与后台的 bm_verify_token 口径保持一致，区别是本函数复用 get_current_user：
    已经做过 token 解析、账号存在性、停用状态校验，这里只再加一道角色判断，
    免得每个写接口各写一遍 if current_user.user_type != "admin"。
    """
    if current_user.user_type != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "需要管理员权限",
                "errors": ["该操作仅限管理员执行"]
            }
        )
    return current_user