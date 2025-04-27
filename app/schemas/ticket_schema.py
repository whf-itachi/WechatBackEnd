from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field


class AttachmentBase(SQLModel):
    """附件基础模型"""
    file_path: str = Field(..., description="文件路径")
    file_type: str = Field(..., description="文件类型")


class AttachmentCreate(AttachmentBase):
    """创建附件请求模型"""
    pass


class AttachmentResponse(SQLModel):
    """附件响应模型"""
    id: int = Field(..., description="附件ID")
    file_path: str = Field(..., description="文件路径")
    file_type: str = Field(..., description="文件类型")
    upload_time: datetime = Field(..., description="上传时间")
    file_name: str = Field(..., description="文件名字")

    class Config:
        from_attributes = True


class TicketBase(SQLModel):
    """工单基础模型"""
    device_model: str = Field(..., description="设备型号")
    customer: str = Field(..., description="客户名称")
    address: Optional[str] = Field(None, description="设备地址")
    fault_phenomenon: str = Field(..., description="故障现象")
    fault_reason: Optional[str] = Field(None, description="故障原因")
    handling_method: Optional[str] = Field(None, description="处理方法")
    handler: str = Field(..., description="故障处理人")


class TicketCreate(TicketBase):
    """创建工单请求模型"""
    pass


class TicketUpdate(SQLModel):
    """更新工单请求模型"""
    device_model: Optional[str] = Field(None, description="设备型号")
    customer: Optional[str] = Field(None, description="客户名称")
    address: Optional[str] = Field(None, description="设备地址")
    fault_phenomenon: Optional[str] = Field(None, description="故障现象")
    fault_reason: Optional[str] = Field(None, description="故障原因")
    handling_method: Optional[str] = Field(None, description="处理方法")
    handler: Optional[str] = Field(None, description="故障处理人")
    # user_id: Optional[int] = Field(None, description="创建用户ID")


class TicketResponse(SQLModel):
    """工单响应模型"""
    id: Optional[int] = Field(None, description="工单ID")
    device_model: Optional[str] = Field(None, description="设备型号")
    customer: Optional[str] = Field(None, description="客户名称")
    address: Optional[str] = Field(None, description="设备地址")
    fault_phenomenon: Optional[str] = Field(None, description="故障现象")
    fault_reason: Optional[str] = Field(None, description="故障原因")
    handling_method: Optional[str] = Field(None, description="处理方法")
    handler: Optional[str] = Field(None, description="故障处理人")
    user_id: Optional[int] = Field(None, description="创建用户ID")
    create_at: Optional[datetime] = Field(None, description="创建时间")
    attachments: List[AttachmentResponse] = Field(default=[], description="附件列表")

    class Config:
        from_attributes = True
