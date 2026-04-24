from fastapi import HTTPException, Request
from starlette import status

from app.logger import get_logger
from app.utils.jwt import verify_token


logger = get_logger('user_router')

async def bm_verify_token(request: Request):
    """
    验证后台管理接口的JWT令牌
    注意：此依赖仅应用于需要管理员权限的接口
    登录、注册、登出等公共接口不应使用此依赖
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

        return payload
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        logger.error(f"验证令牌时出错: {str(e)}")
        raise HTTPException(status_code=401, detail="401无效的认证令牌")
