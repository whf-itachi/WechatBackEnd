from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    """用户表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=50, unique=True)
    phone: str = Field(max_length=11)
    email: str = Field(max_length=100, unique=True)
    password: str = Field(max_length=100)
    user_type: str = Field(max_length=50, default="employee")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)


class UserHistory(SQLModel, table=True):
    """用户修改记录表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")  # 修改者
    changed_id: int = Field(foreign_key="user.id")  # 被修改用户
    before_info: str = Field(max_length=100)  # 修改前
    after_info: str = Field(max_length=100)  # 修改后
    change_reason: str = Field(max_length=300)  # 修改原因
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
