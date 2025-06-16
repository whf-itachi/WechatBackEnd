from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class QuestionCreate(BaseModel):
    question: str
    answers: Optional[str] = None

class QuestionUpdate(BaseModel):
    question: Optional[str] = None
    answers: Optional[str] = None
    status: Optional[int] = None

class QuestionRead(BaseModel):
    id: int
    question: str
    answers: Optional[str] = None
    status: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
