from datetime import datetime
from typing import Optional, List, Union, Dict
from pydantic import BaseModel, Field, RootModel, ConfigDict
from sqlalchemy import false


class SurveyBase(BaseModel):
    title: str = Field(..., max_length=255)
    description: Optional[str] = None


class OptionCreate(BaseModel):
    value: str = Field(..., max_length=255)
    is_other: bool = Field(default=False)


class QuestionCreate(BaseModel):
    text: str
    type: str = Field(..., max_length=50)  # single_choice, multiple_choice, rating, text
    required: bool = Field(default=False)
    options: Optional[List[OptionCreate]] = None


class SurveyCreate(BaseModel):
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    require_login: Optional[bool] = False
    expire_at: Optional[datetime] = None
    questions: List[QuestionCreate]


class SurveyUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None


class SurveyOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    current_responses: int
    expire_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuestionBase(BaseModel):
    text: str
    type: str
    required: bool = True


class OptionOut(BaseModel):
    id: int
    value: str
    is_other: bool = False

    model_config = ConfigDict(from_attributes=True)


class QuestionOut(QuestionBase):
    id: int
    options: List[OptionOut] = []

    model_config = ConfigDict(from_attributes=True)


class SurveyWithQuestions(SurveyOut):
    questions: List[QuestionOut]


class AnswerSubmit(BaseModel):
    question_id: int
    answer_text: Optional[str] = None
    answer_rating: Optional[int] = None
    answer_evaluate: Optional[int] = None
    selected_option_id: Optional[int] = None
    selected_option_ids: Optional[List[int]] = None
    other_text: Optional[Dict[str, str]] = None  # key 为 option_id，value 为自定义值

class ResponseSubmit(BaseModel):
    survey_id: int
    evaluator_id: Optional[int] = None
    answers: List[AnswerSubmit]
    invited_users: Optional[Dict[int, List[int]]] = None

class EvaluationAssignmentOut(BaseModel):
    id: int
    answer_id: int
    evaluator_id: Optional[int] = None
    evaluator_name: Optional[str] = None
    evaluation_score: Optional[int] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class AnswerOutFull(BaseModel):
    question_id: int
    question_text: str
    question_type: str
    required: bool
    answer_text: Optional[str] = None
    answer_rating: Optional[int] = None
    selected_option_id: Optional[int] = None
    selected_option_ids: Optional[List[int]] = None
    other_text: Optional[Dict[str, str]] = None
    evaluations: List[EvaluationAssignmentOut] = []


class SurveyResponseSummary(BaseModel):
    id: int
    submitted_at: datetime
    survey_title: str
    survey_id: Optional[int]

    model_config = ConfigDict(from_attributes=True)

class PaginatedResponse(BaseModel):
    items: List[SurveyResponseSummary]
    total: int


class ResponseDetailOut(BaseModel):
    id: int
    submitted_at: datetime
    survey_title: str
    answers: List[AnswerOutFull]


class RatingQuestionStat(BaseModel):
    question_id: int
    question_text: str
    type: str
    average_score: float

class OptionStatItem(BaseModel):
    option_value: str
    count: int
    percentage: float

class ChoiceQuestionStat(BaseModel):
    question_id: int
    question_text: str
    type: str
    options_stat: List[OptionStatItem]


class SurveyStatisticsResponse(RootModel):
    root: List[Union[ChoiceQuestionStat, RatingQuestionStat]]


class ResponseItem(BaseModel):
    id: int
    submitted_at: datetime
    metadata_answers: Dict[str, str]  # 改名更清晰

class ResponseList(BaseModel):
    total: int
    items: List[ResponseItem]


class SummaryOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    survey_ids: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SummaryDetailOut(SummaryOut):
    relations: List["SummaryRelationOut"]


class SummaryRelationOut(BaseModel):
    survey_id: int
    description: Optional[str] = None

    class Config:
        from_attributes = True


class SummaryCreateIn(BaseModel):
    name: str
    description: Optional[str] = None
    relations: List[SummaryRelationOut]


class SummaryUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    relations: Optional[List[SummaryRelationOut]] = None


class FactoryNoticeCreate(BaseModel):
    company_name: str
    contacts: str


# Pydantic模型：创建单个评价任务的请求体
class CreateEvaluationAssignment(BaseModel):
    question_id: int  # 要评价的问题ID
    evaluation_score: int  # 给出的评分
    evaluator_id: int  # 评价者ID


# 请求体模型
class ShareEvaluationIn(BaseModel):
    temporary_token: str  # Redis存储的键名
    question_id: int  # 问题ID


# 响应体模型
class ShareEvaluationOut(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None
    created_at: datetime


class SurveyOptionOut(BaseModel):
    id: int
    value: str
    is_other: bool

    class Config:
        from_attributes = True


class EvaluationItem(BaseModel):
    question_id: int
    evaluation_score: int


class CreateEvaluationAssignmentBatch(BaseModel):
    response_id: int
    evaluator_id: int
    evaluations: List[EvaluationItem]




