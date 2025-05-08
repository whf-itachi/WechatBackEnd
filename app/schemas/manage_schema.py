from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class DeviceModelResponse(SQLModel):
    """工单响应模型"""
    id: Optional[int] = Field(None, description="ID")
    device_model: Optional[str] = Field(None, description="设备型号")
    create_at: Optional[datetime] = Field(None, description="创建时间")

    class Config:
        from_attributes = True
