from datetime import datetime
from typing import Optional, List

from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, DateTime, func


# ————————————————————————
# 1. 问卷主表 (Survey)
# ————————————————————————

class SurveyTable(SQLModel, table=True):
    __tablename__ = "surveys"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    current_responses: int = Field(default=0)

    created_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))
    updated_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now()))

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
    order: int = Field(default=0)
    text: str
    type: str = Field(max_length=50)  # single_choice, multiple_choice, rating, text
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
    order: int = Field(default=0)

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
    user_name: Optional[str] = Field(default=None)
    company: Optional[str] = Field(default=None)
    phone_number: Optional[str] = Field(default=None)

    submitted_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))

    survey: "SurveyTable" = Relationship(back_populates="responses")
    answers: List["SurveyAnswer"] = Relationship(
        back_populates="response",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# ————————————————————————
# 5. 答案表 (Answer)
# ————————————————————————

class SurveyAnswer(SQLModel, table=True):
    __tablename__ = "survey_answers"

    id: Optional[int] = Field(default=None, primary_key=True)
    response_id: int = Field(foreign_key="survey_responses.id")
    question_id: int = Field(foreign_key="survey_questions.id")

    answer_text: Optional[str] = None
    answer_rating: Optional[int] = None
    submitted_at: datetime = Field(sa_column=Column(DateTime, server_default=func.now()))

    response: "SurveyResponse" = Relationship(back_populates="answers")
    question: "SurveyQuestion" = Relationship(back_populates="answers")
    selected_options: List["SurveyAnswerChoice"] = Relationship(
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
    order: int = Field(default=0)

    answer: "SurveyAnswer" = Relationship(back_populates="selected_options")
    option: "SurveyOption" = Relationship(back_populates="answer_choices")
