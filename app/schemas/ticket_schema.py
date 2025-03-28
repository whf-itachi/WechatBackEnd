from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class TicketCreate(BaseModel):
    device_model: str
    customer: str
    fault_phenomenon: str
    fault_reason: Optional[str] = None
    handling_method: Optional[str] = None
    user_id: int


class TicketUpdate(BaseModel):
    device_model: Optional[str] = None
    customer: Optional[str] = None
    fault_phenomenon: Optional[str] = None
    fault_reason: Optional[str] = None
    handling_method: Optional[str] = None
    user_id: Optional[int] = None


class TicketResponse(BaseModel):
    id: int
    device_model: str
    customer: str
    fault_phenomenon: str
    fault_reason: Optional[str] = None
    handling_method: Optional[str] = None
    user_id: int
    create_at: datetime

    class Config:
        from_attributes = True
