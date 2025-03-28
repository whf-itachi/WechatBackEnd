from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app.db_services.database import AsyncSessionDep
from app.models.user import User
from app.schemas.user_schema import UserCreate, UserUpdate
from fastapi import HTTPException

# 创建用户
async def create_user_service(session: AsyncSessionDep, user_data: UserCreate):
    """创建新用户"""
    print("sds...")

    try:

        new_user = User(**user_data.model_dump())
        print(new_user, '.........')
        print(user_data.model_dump())  # 查看转换后的数据

        session.add(new_user)


        await session.commit()
        await session.refresh(new_user)
        # return new_user
        return new_user.model_dump()
    except Exception as e:
        print("===============:", e)
        await session.rollback()
        raise HTTPException(status_code=400, detail="Email 已被注册")

# 获取所有用户
async def get_users_service(session: AsyncSessionDep):
    """获取所有用户"""
    result = await session.execute(select(User))
    return result.scalars().all()

# 获取单个用户
async def get_user_service(session: AsyncSessionDep, user_id: int):
    """根据 ID 获取用户"""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user

# 更新用户
async def update_user_service(session: AsyncSessionDep, user_id: int, user_data: UserUpdate):
    """更新用户信息"""
    user = await get_user_service(session, user_id)
    for key, value in user_data.dict(exclude_unset=True).items():
        setattr(user, key, value)
    await session.commit()
    await session.refresh(user)
    return user

# 删除用户
async def delete_user_service(session: AsyncSessionDep, user_id: int):
    """删除用户"""
    user = await get_user_service(session, user_id)
    await session.delete(user)
    await session.commit()
    return {"message": "用户删除成功"}
