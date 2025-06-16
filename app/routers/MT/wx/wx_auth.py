import hashlib
from fastapi import Request
from fastapi import APIRouter

from app.logger import get_logger

router = APIRouter()
logger = get_logger('wx_auth_router')
TOKEN = "haitch_wx_auth_202504"

def sign_sha1(signature, timestamp, nonce):
    """
    wx服务器配置 验证
    """
    temp = [TOKEN, timestamp, nonce]
    temp.sort()
    hashcode = hashlib.sha1("".join(temp).encode('utf-8')).hexdigest()
    logger.info(f"加密：{hashcode}，微信返回：{signature}")
    if hashcode == signature:
        return True


@router.api_route("/", methods=["GET", "POST"], summary="微信服务器配置验证")
async def handle_wx(
        signature: str = None,
        timestamp: str = None,
        nonce: str = None,
        echostr: str = None,
        request: Request = None  # 用于接收 POST 请求的 XML 数据
):
    try:
        # GET 请求：验证服务器配置
        if request.method == "GET":
            if sign_sha1(signature, timestamp, nonce):
                return int(echostr)
            else:
                logger.error("验证失败！")
                return "验证失败！"

        # POST 请求：处理微信消息/事件
        elif request.method == "POST":
            body = await request.body()
            logger.info(f"收到微信 POST 消息: {body.decode('utf-8')}")
            # 这里需解析 XML 并逻辑（如回复消息）
            return "success"  # 必须返回 success 告知微信服务器

    except Exception as error:
        return f"微信接口异常: {error}"