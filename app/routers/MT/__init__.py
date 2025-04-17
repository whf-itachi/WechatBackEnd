# 移动端接口
from fastapi import APIRouter
from .user_router import router as user_routers
from .ticket_router import router as ticket_routers
from .wx.wx_auth import router as wx_auth_routers
# 创建父路由实例，配置公共属性
router = APIRouter(
    prefix="/api/v1",          # 全局路径前缀
    tags=["APIv1"]             # 文档分组标签
)

# 注册子路由
router.include_router(user_routers, prefix="/users", tags=["用户管理"])
router.include_router(ticket_routers, prefix="/tickets", tags=["工单管理"])

router.include_router(wx_auth_routers, prefix="/wx_auth", tags=["微信权鉴"])
