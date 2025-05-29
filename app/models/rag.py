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
