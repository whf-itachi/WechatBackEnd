from typing import Optional, List
from datetime import datetime

from pydantic import ConfigDict
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

    model_config = ConfigDict(from_attributes=True)


class TicketBase(SQLModel):
    """工单基础模型"""
    device_model: str = Field(..., description="设备型号")
    customer: str = Field(..., description="客户名称")
    address: Optional[str] = Field(None, description="设备地址")
    fault_phenomenon: str = Field(..., description="故障现象")
    fault_reason: Optional[str] = Field(None, description="故障原因")
    handling_method: Optional[str] = Field(None, description="处理方法")
    handler: Optional[str] = Field(None, description="故障处理人")


class TicketCreate(SQLModel):
    """创建工单请求模型"""
    device_id: int = Field(None, description="设备编号id")
    # device_model: str = Field(..., description="设备型号")
    # customer: str = Field(..., description="客户名称")
    # address: Optional[str] = Field(None, description="设备地址")
    fault_phenomenon: str = Field(..., description="故障现象")
    fault_reason: Optional[str] = Field(None, description="故障原因")
    handling_method: Optional[str] = Field(None, description="处理方法")
    handler: Optional[str] = Field(None, description="故障处理人")


class TicketUpdate(SQLModel):
    device_id: int
    fault_phenomenon: str
    fault_reason: Optional[str] = None
    handling_method: Optional[str] = None
    handler: Optional[str] = None
    delete_list: Optional[List[int]] = None  # 前端传 JSON 数组


class AttachmentOut(SQLModel):
    id: int
    file_path: str
    file_type: str
    upload_time: datetime
    file_name: str

class TicketResponse(SQLModel):
    id: int
    device_model: str
    customer: str
    address: str
    fault_phenomenon: str
    fault_reason: Optional[str]
    handling_method: Optional[str]
    handler: Optional[str]
    user_id: int
    create_at: datetime
    attachments: List[AttachmentOut] = []


class DeviceResponse(SQLModel):
    id: int = Field(primary_key=True)
    device_name: str
    device_type: Optional[str] = None
    processing_range: Optional[str] = None
    create_at: Optional[datetime] = None


# 基础设备信息模型
class DeviceBase(SQLModel):
    id: int
    device_name: str
    device_type: str
    processing_range: Optional[str] = None
    remarks: Optional[str] = None
    created_at: datetime


# 设备详情响应模型（继承基础模型并添加关联信息）
class DeviceDetailResponse(DeviceBase):
    # 设备型号信息
    model_id: int
    device_model: str

    # 工厂信息
    factory_id: Optional[int] = None
    factory_name: Optional[str] = None
    address: Optional[str] = None

    # 客户信息
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    contact_info: Optional[str] = None
    email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
