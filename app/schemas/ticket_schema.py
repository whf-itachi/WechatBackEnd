from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class TicketBase(SQLModel):
    """工单基础模型"""
    device_model: str = Field(..., description="设备型号")
    customer: str = Field(..., description="客户名称")
    fault_phenomenon: str = Field(..., description="故障现象")
    fault_reason: Optional[str] = Field(None, description="故障原因")
    handling_method: Optional[str] = Field(None, description="处理方法")


class TicketCreate(TicketBase):
    """创建工单请求模型"""
    pass


class TicketUpdate(SQLModel):
    """更新工单请求模型"""
    device_model: Optional[str] = Field(None, description="设备型号")
    customer: Optional[str] = Field(None, description="客户名称")
    fault_phenomenon: Optional[str] = Field(None, description="故障现象")
    fault_reason: Optional[str] = Field(None, description="故障原因")
    handling_method: Optional[str] = Field(None, description="处理方法")
    user_id: Optional[int] = Field(None, description="创建用户ID")


class TicketResponse(TicketBase):
    """工单响应模型"""
    id: int = Field(..., description="工单ID")
    user_id: int = Field(..., description="创建用户ID")
    create_at: datetime = Field(..., description="创建时间")

    class Config:
        from_attributes = True
