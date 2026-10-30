import time
import json
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from .logger import get_logger

logger = get_logger('request')

# 仅记录不超过该大小的请求体；超过则一律不读，防止大文件上传把正文吞进内存
MAX_LOG_BODY_BYTES = 64 * 1024

# 需要脱敏的字段（不区分大小写）；命中后统一替换为 ******，避免密码/令牌落盘
_SENSITIVE_KEYS = {
    "password", "token", "authorization", "secret", "api_key",
    "access_token", "refresh_token", "passwd", "pwd",
}


def _redact(obj):
    """递归遮盖敏感字段，保持结构不变便于日志阅读"""
    if isinstance(obj, dict):
        return {
            k: ("******" if k.lower() in _SENSITIVE_KEYS else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


# 日志记录中间件，每次请求前后记录相关信息
class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 记录请求开始时间
        start_time = time.time()

        # 不记录 headers（可能含 Authorization token / cookie 等凭据），避免凭据泄露
        request_info = {
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "client_host": request.client.host if request.client else None,
        }

        # 尝试获取请求体（脱敏后记录）
        # ⚠️ 必须在调用 request.body() 之前判断：一旦读了，整个正文（含上传文件）都会驻留内存，
        # 直到请求结束才释放；多并发上传会直接把进程内存顶爆（线上 OOM 的主要来源之一）。
        try:
            content_type = request.headers.get("content-type", "")
            try:
                content_length = int(request.headers.get("content-length") or 0)
            except (TypeError, ValueError):
                content_length = 0

            if "multipart/form-data" in content_type:
                # 文件上传：只记长度，绝不读正文
                request_info["body"] = f"<文件上传请求，跳过请求体记录，content-length={content_length}>"
            elif content_length > MAX_LOG_BODY_BYTES:
                request_info["body"] = f"<请求体过大（{content_length} 字节），跳过记录>"
            else:
                body = await request.body()
                if body:
                    try:
                        decoded = body.decode()
                    except UnicodeDecodeError:
                        request_info["body"] = "二进制数据，跳过请求体记录"
                    else:
                        try:
                            # 解析为 JSON 后递归脱敏敏感字段
                            parsed = json.loads(decoded)
                            request_info["body"] = _redact(parsed)
                        except (json.JSONDecodeError, ValueError):
                            # 非 JSON 明文（可能含密码等），只记录长度，不记录原文
                            request_info["body"] = f"<非JSON内容，长度 {len(decoded)}>"
        except Exception as e:
            request_info["body"] = f"无法读取请求体: {str(e)}"

        # 记录请求信息
        logger.info(f"收到请求: {json.dumps(request_info, ensure_ascii=False, indent=2)}")

        try:
            # 处理请求（等请求处理完后，再接着走下面的代码逻辑）
            response = await call_next(request)

            # 计算处理时间
            process_time = time.time() - start_time

            # 获取响应信息（不记录响应 headers，避免泄露 Set-Cookie 等）
            response_info = {
                "status_code": response.status_code,
                "process_time": f"{process_time:.3f}s"
            }

            # 记录响应信息
            logger.info(f"请求响应: {json.dumps(response_info, ensure_ascii=False, indent=2)}")

            return response

        except Exception as e:
            # 记录异常信息
            logger.error(f"请求处理异常: {str(e)}", exc_info=True)
            raise
