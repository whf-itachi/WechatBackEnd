from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Text


# 客户公司信息表
class Customer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer: str = Field(max_length=100,unique=True,nullable=False,description="客户公司名称，唯一")
    contact_info: Optional[str] = Field(max_length=20, description="公司联系电话")
    email: Optional[str] = Field(max_length=100, description="公司邮箱")
    created_at: datetime = Field(default_factory=datetime.now)
    # 反向关系：该公司下的所有工厂/客户; 删除客户同时删除客户名下的工厂信息
    factories: List["Factory"] = Relationship(back_populates="customer", cascade_delete=True)


# 设备部署工厂表
class Factory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    factory_name: str = Field(max_length=200, unique=True, nullable=False, description="工厂名称")
    address: Optional[str] = Field(default=None, max_length=300, description="工厂地址")
    remarks: Optional[str] = Field(max_length=500,description="备注信息")
    created_at: datetime = Field(default_factory=datetime.now)

    customer_id: int = Field(foreign_key="customer.id", ondelete="CASCADE")

    # 正向关系：指向公司
    customer: Customer = Relationship(back_populates="factories")
    # 反向关系：该客户拥有的所有设备
    devices: List["DeviceTable"] = Relationship(back_populates="factory", cascade_delete=True)


# 设备型号表
class DeviceModel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_model: str = Field(max_length=100, unique=True, nullable=False)

    created_at: datetime = Field(default_factory=datetime.now)
    # 反向关系：该型号对应的所有设备
    devices: List["DeviceTable"] = Relationship(back_populates="model", cascade_delete=True)


# 设备信息表
class DeviceTable(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_name: str = Field(max_length=50, unique=True, nullable=False,  description="设备编号")
    device_type: str = Field(max_length=100, description="设备类型")
    processing_range: Optional[str] = Field(max_length=255,description="加工范围描述")
    remarks: Optional[str] = Field(max_length=500,description="备注信息")
    created_at: datetime = Field(default_factory=datetime.now)

    # 删除设备型号，联级删除所有该型号设备
    device_model_id: int = Field(foreign_key="devicemodel.id", ondelete="CASCADE")
    # 删除工厂，设备工厂id字段为null
    factory_id: Optional[int] = Field(foreign_key="factory.id", ondelete="SET NULL")

    # 关系
    model: DeviceModel = Relationship(back_populates="devices")
    factory: Optional["Factory"] = Relationship(back_populates="devices")


# 工单附件关系表
class TicketAttachmentLink(SQLModel, table=True):
    ticket_id: int = Field(foreign_key="ticket.id", primary_key=True)
    attachment_id: int = Field(foreign_key="attachment.id", primary_key=True)


# 附件表
class Attachment(SQLModel, table=True):
    """附件表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    file_path: str = Field(max_length=200)  # 仅保存存储目录
    file_name: str = Field(max_length=200)  # 新增文件名
    file_type: str = Field(max_length=50)
    upload_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    tickets: List["Ticket"] = Relationship(
        back_populates="attachments",
        link_model=TicketAttachmentLink
    )


# 工单表
class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    device_model: str = Field(max_length=100, nullable=False)  # 机型, 必填
    customer: str = Field(max_length=200, nullable=False)  # 客户，必填
    address: Optional[str] = Field(sa_type=Text, nullable=True)  # 设备地址，可选
    fault_phenomenon: str = Field(sa_type=Text, nullable=False)  # 故障现象，必填
    fault_reason: Optional[str] = Field(sa_type=Text, nullable=True)  # 故障原因，可选
    handling_method: Optional[str] = Field(sa_type=Text, nullable=True)  # 处理方法，可选
    file_id: str = Field(max_length=200, nullable=True)  # 文档ID
    handler: str = Field(max_length=100)  # 故障处理人
    status: int = Field(default=0)  # 处理状态

    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # 关联关系
    attachments: List["Attachment"] = Relationship(
        back_populates="tickets",
        link_model=TicketAttachmentLink
    )

    histories: List["TicketHistory"] = Relationship(back_populates="ticket")


# 工单修改历史记录表
class TicketHistory(SQLModel, table=True):
    """问题单修改记录表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id")  # 修改的哪条工单
    changer_id: int = Field(foreign_key="user.id")  # 谁修改的
    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  # 修改时间
    original_data: str = Field(sa_type=Text, nullable=False)  # 修改前数据
    modified_data: str = Field(sa_type=Text, nullable=False)  # 修改后数据

    ticket: "Ticket" = Relationship(back_populates="histories")
