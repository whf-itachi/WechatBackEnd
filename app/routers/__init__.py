# routers/__init__.py
from fastapi import APIRouter

# 创建父路由实例，配置公共属性
router = APIRouter(
    prefix="/api/v1",          # 全局路径前缀
    tags=["APIv1"],            # 文档分组标签
    # dependencies=[Depends(verify_token)]  # 全局依赖（如JWT验证）
)

# 导入子路由并合并（需放在最后）
from .user_router import router as user
from .wechat import router as wechat_router

router.include_router(user)
router.include_router(wechat_router)