from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ———————— 问卷 ————————

class SurveyBase(BaseModel):
    title: str
    description: Optional[str] = None
    is_active: bool = True


class SurveyCreate(SurveyBase):
    pass


class SurveyUpdate(SurveyBase):
    title: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class SurveyOut(SurveyBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    participant_count: int = 0

    class Config:
        from_attributes = True


# ———————— 问题 ————————

class QuestionBase(BaseModel):
    text: str
    type: str
    required: bool = False
    order: int = 0


class QuestionCreate(QuestionBase):
    pass


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
    questions: List[QuestionOut] = []


# ———————— 提交答题 ————————

class AnswerSubmit(BaseModel):
    question_id: int
    answer_text: str


class ResponseSubmit(BaseModel):
    answers: List[AnswerSubmit]
