from sqlalchemy import select
from passlib.context import CryptContext
from datetime import timedelta
import bcrypt

from app.db_services.database import AsyncSessionDep
from app.models.user import User
from app.schemas.user_schema import UserCreate, UserUpdate, UserLogin
from app.utils.jwt import create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES
from fastapi import HTTPException
import re
from typing import Tuple

# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        # 如果 bcrypt 验证失败，尝试使用 passlib 验证
        return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """获取密码哈希值"""
    # 使用 bcrypt 生成盐并哈希密码
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def validate_password(password: str) -> bool:
    """验证密码不为空"""
    return bool(password and password.strip())

def validate_email(email: str) -> bool:
    """验证邮箱格式"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def validate_phone(phone: str) -> bool:
    """验证手机号格式"""
    pattern = r'^1[3-9]\d{9}$'
    return bool(re.match(pattern, phone))

async def get_user_by_id(session: AsyncSessionDep, user_id: int) -> User:
    """根据ID获取用户"""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "用户不存在",
                "errors": ["用户不存在"]
            }
        )
        
    return user

async def verify_user_login(session: AsyncSessionDep, login_data: UserLogin) -> Tuple[User, str]:
    """验证用户登录"""
    errors = []
    
    if not login_data.name:
        errors.append("用户名不能为空")
        
    if not login_data.password:
        errors.append("密码不能为空")
        
    if not errors:
        result = await session.execute(select(User).where(User.name == login_data.name))
        user_info = result.scalars().first()
        if not user_info:
            errors.append("用户不存在")
        elif not verify_password(login_data.password, user_info.password):
            errors.append("密码错误")
        elif not user_info.is_active:
            errors.append("用户已被禁用")
    else:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "登录失败",
                "errors": errors
            }
        )
    
    # 生成访问令牌
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user_info.id)}, expires_delta=access_token_expires
    )
    
    return user_info, access_token

# 创建用户
async def create_user_service(session: AsyncSessionDep, user_data: UserCreate) -> Tuple[User, str]:
    """创建新用户"""
    try:
        errors = []
        
        # 验证用户名
        if not user_data.name:
            errors.append("用户名不能为空")
            
        # 验证手机号
        if not user_data.phone:
            errors.append("手机号不能为空")
        elif not validate_phone(user_data.phone):
            errors.append("手机号格式不正确")
            
        # 验证邮箱
        if not user_data.email:
            errors.append("邮箱不能为空")
        elif not validate_email(user_data.email):
            errors.append("邮箱格式不正确")
            
        # 验证密码
        if not user_data.password:
            errors.append("密码不能为空")
            
        # 检查邮箱是否已存在
        if not errors:
            existing_user = await session.execute(
                select(User).where(User.email == user_data.email)
            )
            if existing_user.scalars().first():
                errors.append("邮箱已被注册")
            
        if errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "注册失败: " + str(errors)
                }
            )
            
        # 创建用户数据字典
        user_dict = user_data.model_dump()
        # 对密码进行加密
        user_dict["password"] = get_password_hash(user_dict["password"])
        
        new_user = User(**user_dict)
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)
        
        # 生成访问令牌
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(new_user.id)}, expires_delta=access_token_expires
        )
        
        return new_user, access_token
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "message": "创建用户失败",
                "errors": [str(e)]
            }
        )

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
    try:
        errors = []
        
        # 获取用户
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        
        if not user:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "用户不存在",
                    "errors": ["用户不存在"]
                }
            )
            
        # 验证用户名
        if user_data.name is not None and not user_data.name:
            errors.append("用户名不能为空")
            
        # 验证手机号
        if user_data.phone is not None:
            if not user_data.phone:
                errors.append("手机号不能为空")
            elif not validate_phone(user_data.phone):
                errors.append("手机号格式不正确")
                
        # 验证邮箱
        if user_data.email is not None:
            if not user_data.email:
                errors.append("邮箱不能为空")
            elif not validate_email(user_data.email):
                errors.append("邮箱格式不正确")
            else:
                # 检查邮箱是否已被其他用户使用
                existing_user = await session.execute(
                    select(User).where(User.email == user_data.email, User.id != user_id)
                )
                if existing_user.scalars().first():
                    errors.append("邮箱已被注册")
                    
        # 验证密码
        if user_data.password is not None and not user_data.password:
            errors.append("密码不能为空")
            
        if errors:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "更新用户失败",
                    "errors": errors
                }
            )
            
        # 更新用户数据
        update_data = user_data.model_dump(exclude_unset=True)
        if "password" in update_data:
            update_data["password"] = get_password_hash(update_data["password"])
            
        for field, value in update_data.items():
            setattr(user, field, value)
            
        await session.commit()
        await session.refresh(user)
        
        return user
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail={
                "message": "更新用户失败",
                "errors": [str(e)]
            }
        )

# 删除用户
async def delete_user_service(session: AsyncSessionDep, user_id: int):
    """删除用户"""
    user = await get_user_service(session, user_id)
    await session.delete(user)
    await session.commit()
    return {"message": "用户删除成功"}
