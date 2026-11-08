from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


class User(SQLModel, table=True):
    """用户表

    唯一性约定：
    - `name` 是用户的唯一身份（登录标识），全库唯一；有同名新人请用新名称/加后缀区分；
    - `email` 同样唯一；
    - `wx_openid` 是小程序的微信身份，双向唯一：一个账号只绑一个微信号，
      一个微信号也只能绑一个账号；NULL 表示尚未绑定，MySQL 唯一索引允许多个 NULL。
    - 删除即软删除（is_active=False），行不物理删除，保证出差记录等业务数据可追溯。
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=50, unique=True)
    phone: str = Field(max_length=11)
    email: str = Field(max_length=100, unique=True)
    password: str = Field(max_length=100)
    user_type: str = Field(max_length=50, default="employee")
    is_active: bool = Field(default=True)
    # 微信 openid 只在小程序端使用；换微信号后重新绑定会覆盖这里的值
    wx_openid: Optional[str] = Field(default=None, max_length=64, unique=True)
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
