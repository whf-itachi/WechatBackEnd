from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Text


class DeviceModel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_model: str = Field(max_length=100, unique=True, nullable=False)

    created_at: datetime = Field(default_factory=datetime.now)


class Customer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    customer: str = Field(max_length=200, unique=True, nullable=False)
    created_at: datetime = Field(default_factory=datetime.now)


class TicketAttachmentLink(SQLModel, table=True):
    ticket_id: int = Field(foreign_key="ticket.id", primary_key=True)
    attachment_id: int = Field(foreign_key="attachment.id", primary_key=True)


class Attachment(SQLModel, table=True):
    """附件表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    file_path: str = Field(max_length=200)
    file_type: str = Field(max_length=50)
    upload_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    tickets: List["Ticket"] = Relationship(
        back_populates="attachments",
        link_model=TicketAttachmentLink
    )


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

    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # 关联关系
    attachments: List["Attachment"] = Relationship(
        back_populates="tickets",
        link_model=TicketAttachmentLink
    )

    histories: List["TicketHistory"] = Relationship(back_populates="ticket")


class TicketHistory(SQLModel, table=True):
    """问题单修改记录表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id")  # 修改的哪条工单
    changer_id: int = Field(foreign_key="user.id")  # 谁修改的
    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))  # 修改时间
    original_data: str = Field(sa_type=Text, nullable=False)  # 修改前数据
    modified_data: str = Field(sa_type=Text, nullable=False)  # 修改后数据

    ticket: "Ticket" = Relationship(back_populates="histories")
