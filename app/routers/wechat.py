# 微信消息处理路由
from fastapi import APIRouter

from app.db_services.database import AsyncSessionDep
from app.services.user_service import get_users_service

router = APIRouter()

@router.get("/users")
async def get_users(session: AsyncSessionDep):
    return await get_users_service(session)
