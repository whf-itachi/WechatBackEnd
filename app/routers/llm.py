# 其他业务路由

# 导入APIRouter
from fastapi import APIRouter


# 实例化APIRouter实例
router = APIRouter(prefix="/llm", tags=["业务接口"])


# 注册具体方法
@router.get("/")
async def index():
    """
    默认访问链接
    """
    return {
        "code": 200,
        "msg": "Hello llm!"
    }