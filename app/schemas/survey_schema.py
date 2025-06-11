from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ———————— 问卷 ————————

class SurveyBase(BaseModel):
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    is_active: bool = True


class OptionCreate(BaseModel):
    value: str = Field(..., max_length=255)
    order: int = Field(default=0)


class QuestionCreate(BaseModel):
    text: str
    type: str = Field(..., max_length=50)  # single_choice, multiple_choice, rating, text
    required: bool = Field(default=False)
    order: int = Field(default=0)
    options: Optional[List[OptionCreate]] = None


class SurveyCreate(BaseModel):
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    questions: List[QuestionCreate]


class SurveyUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SurveyOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    is_active: bool
    current_responses: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ———————— 问题 ————————

class QuestionBase(BaseModel):
    text: str
    type: str
    required: bool = False
    order: int = 0


class QuestionUpdate(QuestionBase):
    text: Optional[str] = None
    type: Optional[str] = None
    required: Optional[bool] = None
    order: Optional[int] = None


class OptionOut(BaseModel):
    id: int
    value: str
    order: int

    class Config:
        from_attributes = True


class QuestionOut(QuestionBase):
    id: int
    options: List[OptionOut] = []

    class Config:
        from_attributes = True


# ———————— 问卷完整结构 ————————

class SurveyWithQuestions(SurveyOut):
    questions: List[QuestionOut]


# ———————— 提交答题 ————————

class AnswerSubmit(BaseModel):
    question_id: int
    answer_text: Optional[str] = None  # 文本题
    answer_rating: Optional[int] = None  # 评分题
    selected_option_ids: Optional[List[int]] = None  # 选择题（单选或多选）


class ResponseSubmit(BaseModel):
    answers: List[AnswerSubmit]
