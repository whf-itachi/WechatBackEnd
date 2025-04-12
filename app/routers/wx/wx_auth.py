import hashlib

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


@router.get("/", summary="微信服务器配置验证")
async def handle_wx(signature, timestamp, nonce, echostr):
    try:
        if sign_sha1(signature, timestamp, nonce):
            return int(echostr)
        else:
            logger.error("加密字符串 不等于 微信返回字符串，验证失败！！！")
            return "验证失败！"
    except Exception as error:
        return f"微信服务器配置验证出现异常:{error}"