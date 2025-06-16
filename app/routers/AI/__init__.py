# 后台管理接口
from fastapi import APIRouter

from app.routers.AI.assistant import router as assistant_router

# 创建父路由实例，配置公共属性
router = APIRouter(
    prefix="/AI"  # 全局路径前缀
)


# 注册子路由
router.include_router(assistant_router, prefix="/assistant")  # 智能客服模块
