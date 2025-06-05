from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import router  # 从 __init__.py 导入聚合后的路由
from app.logger import setup_logger, RequestLoggerMiddleware
from app.utils.redis import init_redis, close_redis

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

# 添加请求日志中间件（确保最先执行）
app.add_middleware(RequestLoggerMiddleware)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # 允许的前端域名
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有HTTP方法
    allow_headers=["*"],  # 允许所有请求头
    expose_headers=["*"],  # 暴露所有响应头
)

# 注册路由
app.include_router(router)


if __name__ == "__main__":
    logger.info("正在启动服务器...")
    uvicorn.run("__main__:app", host="0.0.0.0", port=8000, reload=True)