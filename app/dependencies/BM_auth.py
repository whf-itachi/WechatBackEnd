from fastapi import HTTPException, Request
from starlette import status

from app.logger import get_logger
from app.utils.jwt import verify_token


logger = get_logger('user_router')

async def bm_verify_token(request: Request):
    try:
        path = request.url.path
        if path.endswith('/login'):
            pass
        else:
            authorization = request.headers.get("Authorization")
            # logger.info("get the Authorization is:%s, %s", authorization, type(authorization))
            if not authorization:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="未提供认证信息"
                )
            payload = verify_token(authorization)
            if not payload:
                raise HTTPException(status_code=401, detail="401无效的认证令牌")

            if payload.get("user_type") != "admin":
                raise HTTPException(status_code=403, detail="403需要管理员权限")

            return payload
    except Exception as e:
        logger.error("error: ", e)
        raise HTTPException(status_code=401, detail="401无效的认证令牌")
