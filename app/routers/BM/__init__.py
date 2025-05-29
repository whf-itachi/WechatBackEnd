# 后台管理接口
from fastapi import APIRouter

from app.routers.BM.user_manager import router as user_manage_router
from app.routers.BM.ticket_manager import router as ticket_manage_router
from app.routers.BM.bm_manager import router as bm_manage_router
from app.routers.BM.rag_manager import router as rag_manage_router

# 创建父路由实例，配置公共属性
router = APIRouter(
    prefix="/BM"  # 全局路径前缀
)


# 注册子路由
router.include_router(user_manage_router, prefix="/user")  # 用户模块
router.include_router(ticket_manage_router, prefix="/ticket")  # 工单模块
router.include_router(bm_manage_router, prefix="/manage")  # 后台管理
router.include_router(rag_manage_router, prefix="/rag")  # 后台管理
