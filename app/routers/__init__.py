# routers/__init__.py
from fastapi import APIRouter
from app.routers.user_router import router as user_router
from app.routers.ticket_router import router as ticket_router
from app.routers.wx.wx_auth import router as wx_auth_router
# 创建父路由实例，配置公共属性
router = APIRouter(
    prefix="/api/v1",          # 全局路径前缀
    tags=["APIv1"]             # 文档分组标签
)

# 注册子路由
router.include_router(user_router, prefix="/users", tags=["用户管理"])
router.include_router(ticket_router, prefix="/tickets", tags=["工单管理"])

router.include_router(wx_auth_router, prefix="/wx_auth", tags=["微信权鉴"])
