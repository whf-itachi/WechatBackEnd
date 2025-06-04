# RAG知识库相关类

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Text
from sqlmodel import SQLModel, Field


class Question(SQLModel, table=True):
    """反馈问题表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    question: str = Field(sa_type=Text, nullable=False)  # 问题内容
    answers: str = Field(sa_type=Text, nullable=True)  # 回答内容
    status: int = Field(default=0)  # 处理状态
    is_delete: int = Field(default=0)  # 软删除

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = Field(default=None)


class Documents(SQLModel, table=True):
    """知识库上传文档"""
    id: Optional[int] = Field(default=None, primary_key=True)
    file_name: str = Field(max_length=200, unique=True, nullable=False)  # 文档名称
    tag: str = Field(max_length=100, nullable=False)  # 文档标签
    status: int = Field(default=0)  # 处理状态
    is_delete: int = Field(default=0)  # 软删除

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
