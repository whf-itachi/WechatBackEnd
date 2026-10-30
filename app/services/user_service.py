from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
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
        ident = (login_data.name or "").strip()
        # name 是唯一身份，但登录框也接受手机号，所以两列都查；
        # 姓名命中优先（身份标识），其次手机号。
        rows = (
            await session.execute(
                select(User).where(or_(User.name == ident, User.phone == ident))
            )
        ).scalars().all()

        # 停用（软删除）的账号不参与登录
        active = [u for u in rows if u.is_active]
        by_name = [u for u in active if u.name == ident]
        by_phone = [u for u in active if u.phone == ident]
        user_info = (by_name or by_phone or [None])[0]

        if not rows:
            errors.append("用户不存在")
        elif user_info is None:
            errors.append("该账号已停用")
        elif not verify_password(login_data.password, user_info.password):
            errors.append("密码错误")
    
    # 检查是否有错误
    if errors:
        raise HTTPException(
            status_code=401,
            detail={
                # 把首个具体原因带出去（"该账号已停用"/"密码错误"…），
                # 前端只展示 message，否则软删除后用户只会看到笼统的"登录失败"
                "message": "登录失败：" + errors[0],
                "errors": errors
            }
        )

    # 生成访问令牌
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"user_id": str(user_info.id), "user_type": str(user_info.user_type)}, expires_delta=access_token_expires
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
            
        # name 是唯一身份、email 也是唯一列：分别检查，给出明确提示
        # （之前只查 email，姓名重复会直接撞唯一索引变成 500）
        email_text = str(user_data.email)
        if not errors:
            if (
                await session.execute(select(User.id).where(User.name == user_data.name))
            ).first():
                errors.append("用户名已被占用")
            elif (
                await session.execute(select(User.id).where(User.email == email_text))
            ).first():
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
        user_dict["email"] = email_text
        # 对密码进行加密
        user_dict["password"] = get_password_hash(user_dict["password"])

        new_user = User(**user_dict)
        session.add(new_user)
        try:
            await session.commit()
        except IntegrityError:
            # 并发下唯一键兜底（name / email 都可能撞）
            await session.rollback()
            raise HTTPException(
                status_code=400,
                detail={"message": "注册失败: 用户名或邮箱已被占用"}
            )
        await session.refresh(new_user)
        
        # 生成访问令牌
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            # 修正后代码（补充用户类型）
            data={"user_id": str(new_user.id), "user_type": str(new_user.user_type)}, expires_delta=access_token_expires
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
    """获取所有用户（不含已停用/软删除的账号）"""
    result = await session.execute(select(User).where(User.is_active == True))  # noqa: E712
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
                    select(User).where(User.email == str(user_data.email), User.id != user_id)
                )
                if existing_user.scalars().first():
                    errors.append("邮箱已被注册")

        # 用户名是唯一身份，改名时同样要查重（否则会直接撞唯一索引）
        if user_data.name is not None and user_data.name:
            name_conflict = await session.execute(
                select(User.id).where(User.name == user_data.name, User.id != user_id)
            )
            if name_conflict.first():
                errors.append("用户名已被占用")
                    
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

# 删除用户（软删除：只置 is_active=False，行与历史数据都保留）
async def delete_user_service(session: AsyncSessionDep, user_id: int):
    """删除用户 —— 软删除

    不物理删除 user 行：出差记录等业务数据通过 user_id 关联，
    物理删除会连带抹掉历史账目。
    注意：name 是唯一身份（全库唯一），因此停用账号仍占用该名称，
    不能靠"重新注册"来恢复；需要恢复时由管理员通过改库或启用接口处理。
    """
    user = await get_user_service(session, user_id)
    if not user.is_active:
        return {"message": "该用户已处于停用状态"}
    user.is_active = False
    user.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"message": "用户已删除（停用），历史数据保留"}
