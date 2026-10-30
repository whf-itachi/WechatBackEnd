from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.db_services.database import get_db
from app.logger import get_logger
from app.models.user import User
from app.utils.jwt import verify_token


logger = get_logger('user_router')

async def bm_verify_token(request: Request, db: AsyncSession = Depends(get_db)):
    """
    验证后台管理接口的JWT令牌
    注意：此依赖仅应用于需要管理员权限的接口
    登录、注册、登出等公共接口不应使用此依赖

    除了校验 token 里的 user_type，还会回查一次 is_active：
    用户被软删除（停用）后，手里的旧 token 必须立即失效，不能等它自然过期。
    """
    try:
        authorization = request.headers.get("Authorization")
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未提供认证信息"
            )
        
        # 移除 "Bearer " 前缀（如果存在）
        if authorization.startswith("Bearer "):
            authorization = authorization[7:]
        
        payload = verify_token(authorization)
        if not payload:
            raise HTTPException(status_code=401, detail="401无效的认证令牌")

        if payload.get("user_type") != "admin":
            raise HTTPException(status_code=403, detail="403需要管理员权限")

        # 软删除/停用校验（token 里不带状态，只能回查库）
        user_id = payload.get("user_id")
        if user_id is not None:
            row = (
                await db.execute(select(User.is_active).where(User.id == int(user_id)))
            ).first()
            if row is None:
                raise HTTPException(status_code=401, detail="401账号不存在")
            if not row[0]:
                raise HTTPException(status_code=401, detail="401账号已停用")

        return payload
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        logger.error(f"验证令牌时出错: {str(e)}")
        raise HTTPException(status_code=401, detail="401无效的认证令牌")
