from datetime import datetime
from typing import Optional, List

from fastapi.openapi.models import Operation
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, DateTime, func, UniqueConstraint


# ————————————————————————
# 1. 问卷主表 (Survey)
# ————————————————————————
class SurveyTable(SQLModel, table=True):
    __tablename__ = "surveys"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    current_responses: int = Field(default=0)
    require_login: bool = Field(default=False, description="是否需要登录才能填写问卷")

    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now()))

    expire_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime),
        description="问卷填写的截止时间，可为空表示无截止日期"
    )
    questions: List["SurveyQuestion"] = Relationship(
        back_populates="survey",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    responses: List["SurveyResponse"] = Relationship(
        back_populates="survey",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ————————————————————————
# 2. 问题表 (Question)
# ————————————————————————
class SurveyQuestion(SQLModel, table=True):
    __tablename__ = "survey_questions"

    id: Optional[int] = Field(default=None, primary_key=True)
    survey_id: int = Field(foreign_key="surveys.id")
    text: str
    type: str = Field(max_length=50)  # single_choice, multiple_choice, rating, text, meta_data, evaluate, target
    required: bool = Field(default=False)

    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))

    survey: "SurveyTable" = Relationship(back_populates="questions")
    options: List["SurveyOption"] = Relationship(
        back_populates="question",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    answers: List["SurveyAnswer"] = Relationship(
        back_populates="question",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ————————————————————————
# 3. 选项表 (Option)
# ————————————————————————
class SurveyOption(SQLModel, table=True):
    __tablename__ = "survey_options"

    id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="survey_questions.id")
    value: str = Field(max_length=255)
    is_other: bool = Field(default=False)  # 标记是否为"其他，请说明"

    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))

    question: "SurveyQuestion" = Relationship(back_populates="options")
    answer_choices: List["SurveyAnswerChoice"] = Relationship(back_populates="option")


# ————————————————————————
# 4. 回答记录表 (Response)
# ————————————————————————
class SurveyResponse(SQLModel, table=True):
    __tablename__ = "survey_responses"

    id: Optional[int] = Field(default=None, primary_key=True)
    survey_id: int = Field(foreign_key="surveys.id")
    temporary_token: Optional[str] = Field(default=None)  # 临时记录的令牌
    submitted_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))

    survey: "SurveyTable" = Relationship(back_populates="responses")
    answers: List["SurveyAnswer"] = Relationship(
        back_populates="response",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# —————————————————————
# 5. 答案表 (Answer)
# —————————————————————
class SurveyAnswer(SQLModel, table=True):
    __tablename__ = "survey_answers"

    id: Optional[int] = Field(default=None, primary_key=True)
    response_id: int = Field(foreign_key="survey_responses.id")  # 哪个回答表
    question_id: int = Field(foreign_key="survey_questions.id")  # 的哪个问题

    # 普通答案内容
    answer_text: Optional[str] = None
    answer_rating: Optional[int] = None

    # 关联关系
    response: "SurveyResponse" = Relationship(back_populates="answers")
    question: "SurveyQuestion" = Relationship(back_populates="answers")
    selected_options: List["SurveyAnswerChoice"] = Relationship(
        back_populates="answer",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    assignments: List["SurveyEvaluationAssignment"] = Relationship(
        back_populates="answer",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ————————————————————————
# 6. 多选答案关联表 (AnswerChoice)
# ————————————————————————
class SurveyAnswerChoice(SQLModel, table=True):
    __tablename__ = "survey_answer_choices"

    answer_id: int = Field(foreign_key="survey_answers.id", primary_key=True)
    option_id: int = Field(foreign_key="survey_options.id", primary_key=True)
    custom_value: Optional[str] = None  # 如果是"其他，请说明"，则填这个字段

    answer: "SurveyAnswer" = Relationship(back_populates="selected_options")
    option: "SurveyOption" = Relationship(back_populates="answer_choices")


# ————————————————————————
# 7. 多个问卷汇总问卷表
# ————————————————————————
class SurveySummaryTable(SQLModel, table=True):
    __tablename__ = "survey_summary_tables"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255)  # 汇总表的名称
    description: Optional[str] = Field(default=None)  # 描述
    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))  # 创建时间

    relations: List["SurveySummaryLinks"] = Relationship(back_populates="summary",
                                                         sa_relationship_kwargs={"lazy": "selectin"})


# ————————————————————————
# 8. 汇总问卷关联关系表
# ————————————————————————
class SurveySummaryLinks(SQLModel, table=True):
    __tablename__ = "survey_summary_links"
    __table_args__ = (
        UniqueConstraint("summary_id", "survey_id", name="uq_summary_survey"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    summary_id: int = Field(foreign_key="survey_summary_tables.id")
    survey_id: int = Field(foreign_key="surveys.id")
    description: Optional[str] = None

    summary: SurveySummaryTable = Relationship(back_populates="relations")



# —————————————————————
# 9. 绩效评价任务表
# —————————————————————
class SurveyEvaluationAssignment(SQLModel, table=True):
    __tablename__ = "survey_evaluation_assignments"

    id: Optional[int] = Field(default=None, primary_key=True)

    answer_id: int = Field(foreign_key="survey_answers.id")  # 关联哪一个答案
    evaluator_name: str  # 评价者名称
    evaluator_id: Optional[int] = None  # 提交者id
    evaluation_score: Optional[int] = None  # 给出的评分
    identity: Optional[str] = None  # 身份
    status: str = Field(default="pending")  # pending / completed

    created_at: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now()),
        description="创建时间"
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now()),
        description="更新时间"
    )
    # 关系
    answer: "SurveyAnswer" = Relationship(back_populates="assignments")


# 工厂须知登记记录
class FactoryNoticeHistory(SQLModel, table=True):
    __tablename__ = "factory_notice_history"
    id: Optional[int] = Field(primary_key=True)
    company_name: str = Field(max_length=200, default=None)
    contacts: str = Field(max_length=200, default=None)
    created_at: datetime = Field(default_factory=datetime.now)
