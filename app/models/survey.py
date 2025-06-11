from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field
from sqlalchemy import func, Column, DateTime


# ————————————————————————
# 问卷相关模型
# ————————————————————————

class SurveyTable(SQLModel, table=True):
    """问卷表"""
    __tablename__ = "survey_table"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)

    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now()))


class SurveyQuestion(SQLModel, table=True):
    """问题表"""
    __tablename__ = "survey_question"

    id: Optional[int] = Field(default=None, primary_key=True)
    survey_id: int = Field(foreign_key="survey_table.id")  # 关联到问卷表
    order: int = Field(default=0)  # 在问卷表中的顺序

    text: str  # 问题内容
    type: str = Field(max_length=50)  # 问题类型: single_choice, multiple_choice, rating, text
    required: bool = Field(default=False)  # 是否必填
    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now()))


class SurveyOption(SQLModel, table=True):
    """选项表"""
    __tablename__ = "survey_option"

    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="survey_question.id")  # 关联问题表id
    value: str = Field(max_length=255)  # 选项内容
    order: int = Field(default=0)  # 显示顺序
    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))


class SurveyResponse(SQLModel, table=True):
    """问卷提交记录表"""
    __tablename__ = "survey_response"

    id: Optional[int] = Field(default=None, primary_key=True)
    survey_id: int = Field(foreign_key="survey_table.id")  # 哪张问卷
    user_name: Optional[str] = Field(nullable=True)  # 谁提交的
    submitted_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))


class SurveyAnswer(SQLModel, table=True):
    """答题记录表"""
    __tablename__ = "survey_answer"

    id: Optional[int] = Field(default=None, primary_key=True)
    response_id: int = Field(foreign_key="survey_response.id")  # 谁回答的
    question_id: int = Field(foreign_key="survey_question.id")  # 哪个问题
    answer_text: str  # 回答内容
    submitted_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))
