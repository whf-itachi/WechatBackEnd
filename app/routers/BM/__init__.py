# 后台管理接口
from fastapi import APIRouter, Depends

from app.dependencies.BM_auth import bm_verify_token
from app.routers.BM.user_manager import router as user_manage_router

# 创建父路由实例，配置公共属性
router = APIRouter(
    prefix="/BM",             # 全局路径前缀
    dependencies=[Depends(bm_verify_token)]  # 该分组路由全部实现token校验
)


# 注册子路由
router.include_router(user_manage_router)  # 用户管理
