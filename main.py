import uvicorn
from fastapi import FastAPI

from app.routers import router  # 从 __init__.py 导入聚合后的路由

app = FastAPI()
app.include_router(router)  # 一次性注册所有路由


if __name__ == "__main__":
    # uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
    uvicorn.run("__main__:app", host="0.0.0.0", port=8001, reload=True)