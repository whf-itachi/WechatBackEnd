"""微信小程序服务端凭证交换。

安全约定：
- 小程序端只把 wx.login() 拿到的一次性 code 传给后端；
- openid 必须由后端用 AppID + AppSecret 向微信换取，前端绝不传 openid 明文，
  否则任何人伪造一个字符串就能登录别人的账号；
- AppSecret 只存在后端 .env，不下发、不写日志、不进异常信息。
"""
import httpx
from fastapi import HTTPException

from app.config import settings
from app.logger import get_logger

logger = get_logger("wx_api")

JSCODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"

# 微信 jscode2session 错误码 -> 给用户看的中文提示。
# 微信的 errmsg 是英文且常带一串 rid 追踪串，例如
# "invalid code, rid: 6af04e22-4a6bdb8b-14d3e910"，直接透出就是一串字符，
# 也可能泄露内部排障信息。原始 errcode/errmsg 只写日志，前端只拿中文提示。
WX_ERRCODE_MESSAGES = {
    -1: "微信服务繁忙，请稍后重试",
    40013: "小程序 AppID 配置有误，请联系管理员",
    40014: "微信登录凭证无效，请重新进入小程序",
    40029: "微信登录凭证已失效，请退出小程序重新进入；若反复出现请联系管理员",
    40125: "小程序密钥配置有误，请联系管理员",
    40163: "微信登录凭证已被使用，请重新进入小程序",
    40226: "该微信账号暂时无法登录，请联系管理员",
    41008: "缺少微信登录凭证，请重新进入小程序",
    45009: "微信接口调用超出限额，请稍后再试",
    45011: "微信登录过于频繁，请稍后再试",
}
WX_LOGIN_FAILED_MESSAGE = "微信登录失败，请重新进入小程序重试；若反复出现请联系管理员"


def _wx_error_message(errcode) -> str:
    """把微信 errcode 转成中文提示；未知/缺失错误码统一用兜底文案。"""
    try:
        key = int(errcode)
    except (TypeError, ValueError):
        key = None
    return WX_ERRCODE_MESSAGES.get(key, WX_LOGIN_FAILED_MESSAGE)


async def code_to_openid(code: str) -> str:
    """用一次性 code 换取 openid，失败时抛出可直接返回给前端的 HTTPException。"""
    if not code or not code.strip():
        raise HTTPException(status_code=400, detail="缺少微信登录凭证 code")

    if not settings.WX_APPID or not settings.WX_APPSECRET:
        logger.error("未配置 WX_APPID / WX_APPSECRET，无法完成微信登录")
        raise HTTPException(
            status_code=500,
            detail="服务端未配置微信小程序 AppSecret，请在 .env 中填写 WX_APPSECRET",
        )

    params = {
        "appid": settings.WX_APPID,
        "secret": settings.WX_APPSECRET,
        "js_code": code.strip(),
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(JSCODE2SESSION_URL, params=params)
            payload = response.json()
    except Exception as exc:
        logger.error(f"调用微信 jscode2session 失败: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="微信登录服务暂不可用，请稍后重试")

    if not isinstance(payload, dict):
        logger.warning(f"微信登录返回异常内容: {type(payload).__name__}")
        raise HTTPException(status_code=502, detail="微信登录服务暂不可用，请稍后重试")

    openid = payload.get("openid")
    if not openid:
        # 原始 errcode/errmsg 只落日志，方便排查；不拼进返回给小程序的提示
        logger.warning(
            f"微信登录失败: errcode={payload.get('errcode')}, errmsg={payload.get('errmsg')}"
        )
        raise HTTPException(
            status_code=400,
            detail=_wx_error_message(payload.get("errcode")),
        )
    return openid
