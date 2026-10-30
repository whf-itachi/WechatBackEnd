from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers import router  # 从 __init__.py 导入聚合后的路由
from app.logger import setup_logger, RequestLoggerMiddleware
from app.utils.redis import init_redis, close_redis
from app.config import settings
from app.utils.responses import ApiResponse
from app.utils.enveloping_route import EnvelopingRoute

# 设置日志系统
logger = setup_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 初始化redis
    await init_redis()

    yield
    # 关闭redis
    await close_redis()


app = FastAPI(lifespan=lifespan)

# 成功响应统一信封：所有 JSON 成功响应包成 {code, message, data}
app.router.route_class = EnvelopingRoute

# 添加请求日志中间件（确保最先执行）
app.add_middleware(RequestLoggerMiddleware)

# 配置CORS：仅允许白名单来源携带凭据，禁止通配 "*"（避免任意站点带凭据调用 API）
allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
    expose_headers=["*"],  # 暴露所有响应头
)


# ---------------- 全局异常处理器：统一错误响应信封 ----------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or detail.get("error") or "请求失败")
        if detail.get("errors"):
            # 细节只落日志，不返回给客户端
            logger.warning(f"HTTP {exc.status_code} {request.url.path}: {detail}")
    else:
        message = str(detail)
    enveloped = ApiResponse(code=exc.status_code, message=message, data=None)
    return JSONResponse(status_code=exc.status_code, content=enveloped.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # exc.errors() 的 ctx 里可能带着 ValueError 等非 JSON 对象，直接 model_dump 会抛
    # TypeError 把 422 变成 500，这里统一转成字符串再返回
    details = []
    for err in exc.errors():
        item = {k: v for k, v in err.items() if k != "ctx"}
        ctx = err.get("ctx")
        if isinstance(ctx, dict):
            item["ctx"] = {k: str(v) for k, v in ctx.items()}
        details.append(item)
    enveloped = ApiResponse(code=422, message="请求参数校验失败", data=details)
    return JSONResponse(status_code=422, content=enveloped.model_dump())


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.error(f"未处理异常: {exc}", exc_info=True)
    enveloped = ApiResponse(code=500, message="服务器内部错误", data=None)
    return JSONResponse(status_code=500, content=enveloped.model_dump())


# 注册路由
app.include_router(router)


if __name__ == "__main__":
    logger.info("正在启动服务器...")
    uvicorn.run("__main__:app", host="0.0.0.0", port=8000, reload=True)
