# 后台用户管理模块
from fastapi import Request
from fastapi import APIRouter

from app.logger import get_logger

router = APIRouter()
logger = get_logger('user_management_router')


@router.api_route("/login", methods=["POST"], summary="后台用户登录接口")
async def bm_user_login(
        request: Request = None  # 用于接收 POST 请求的 XML 数据
):
    try:
        body = await request.body()
        logger.info(f"收到微信 POST 消息: {body.decode('utf-8')}")
        # 这里需解析 XML 并逻辑（如回复消息）
        return "success"  # 必须返回 success 告知微信服务器

    except Exception as error:
        return f"微信接口异常: {error}"