# routers/__init__.py
from fastapi import APIRouter
from app.routers.MT import router as mt_router
from app.routers.BM import router as bm_router
from app.routers.AI import router as ai_router

# 创建父路由实例，配置公共属性
router = APIRouter()

# 注册子路由
router.include_router(mt_router, tags=["ics移动端接口"])
router.include_router(bm_router, tags=["ics后台接口"])
router.include_router(ai_router, tags=["AI助手接口"])

