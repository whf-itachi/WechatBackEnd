import time
import json
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from .logger import get_logger

logger = get_logger('request')


# 日志记录中间件，每次请求前记录该请求的相关信息
class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 记录请求开始时间
        start_time = time.time()
        # 获取请求信息
        request_info = {
            "method": request.method,
            "url": str(request.url),
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "headers": dict(request.headers),
            "client_host": request.client.host if request.client else None,
            "client_port": request.client.port if request.client else None
        }
        
        # 尝试获取请求体
        try:
            body = await request.body()
            if body:
                request_info["body"] = body.decode()
        except Exception as e:
            request_info["body"] = f"无法读取请求体: {str(e)}"
        
        # 记录请求信息
        logger.info(f"收到请求: {json.dumps(request_info, ensure_ascii=False, indent=2)}")
        
        try:
            # 处理请求（等请求处理完后，再接着走下面的代码逻辑）
            response = await call_next(request)
            
            # 计算处理时间
            process_time = time.time() - start_time
            
            # 获取响应信息
            response_info = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "process_time": f"{process_time:.3f}s"
            }
            
            # 记录响应信息
            logger.info(f"请求响应: {json.dumps(response_info, ensure_ascii=False, indent=2)}")
            
            return response
            
        except Exception as e:
            # 记录异常信息
            logger.error(f"请求处理异常: {str(e)}", exc_info=True)
            raise 