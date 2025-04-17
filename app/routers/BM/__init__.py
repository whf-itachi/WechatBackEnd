# 后台管理接口
from fastapi import APIRouter
from app.routers.BM.user_manager import router as user_manage_router

# 创建父路由实例，配置公共属性
router = APIRouter(
    prefix="/BM",             # 全局路径前缀
    tags=["back_management"]  # 文档分组标签
)

# 注册子路由
router.include_router(user_manage_router, prefix="/users", tags=["用户管理"])
