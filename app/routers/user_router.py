from fastapi import APIRouter

from app.db_services.database import AsyncSessionDep
from app.services.user_service import (
    create_user_service, get_users_service, get_user_service, update_user_service, delete_user_service
)
from app.schemas.user_schema import UserCreate, UserResponse, UserUpdate
from typing import List

router = APIRouter(prefix="/users", tags=["用户管理"])

# 创建用户
@router.post("/", response_model=UserResponse)
async def create_user(user_data: UserCreate, session: AsyncSessionDep):
    try:
        result = await create_user_service(session, user_data)
        print(type(result))
        print(result)
        print("------")

        return result

    except Exception as e:
        print("sd...sd: ", e)
        raise EOFError

# 查询所有用户
@router.get("/", response_model=List[UserResponse])
async def get_users(session: AsyncSessionDep):
    return await get_users_service(session)

# 根据用户id查询用户信息
@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, session: AsyncSessionDep):
    return await get_user_service(session, user_id)

# 根据用户id修改用户信息
@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: int, user_data: UserUpdate, session: AsyncSessionDep):
    return await update_user_service(session, user_id, user_data)

# 根据用户id删除用户
@router.delete("/{user_id}")
async def delete_user(user_id: int, session: AsyncSessionDep):
    return await delete_user_service(session, user_id)
