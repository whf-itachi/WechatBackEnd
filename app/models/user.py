from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    """用户信息表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name_en: str = Field(default=None, max_length=100)
    name_zh: str = Field(default=None, max_length=50)
    phone: str = Field(regex=r"^1[3-9]\d{9}$")
    email: str = Field(max_length=50)
    password: str = Field(max_length=200)  # 存储密码的哈希值
    is_active: bool = Field(default=True)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserHistory(SQLModel, table=True):
    """用户修改记录表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")  # 修改者
    changed_id: int = Field(foreign_key="user.id")  # 被修改用户
    before_info: str = Field(max_length=100)  # 修改前
    after_info: str = Field(max_length=100)  # 修改后
    change_reason: str = Field(max_length=300)  # 修改原因

    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
