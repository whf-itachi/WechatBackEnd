from datetime import datetime, timezone
from typing import Optional, List
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Text, Enum

class TicketAttachmentLink(SQLModel, table=True):
    ticket_id: int = Field(foreign_key="ticket.id", primary_key=True)
    attachment_id: int = Field(foreign_key="attachment.id", primary_key=True)


class AttachmentType(str, Enum):
    IMAGE = "image"
    DOCUMENT = "document"
    VIDEO = "video"


class Attachment(SQLModel, table=True):
    """附件表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id")
    file_path: str = Field(max_length=200)
    file_type: str = Field(max_length=50)
    upload_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    tickets: List["Ticket"] = Relationship(
        back_populates="attachments",
        link_model=TicketAttachmentLink
    )


class TicketBase(SQLModel):
    device_model: str = Field(max_length=100, nullable=False)  # 机型, 必填
    customer: str = Field(max_length=200)  # 客户
    fault_phenomenon: str = Field(sa_type=Text, nullable=False)  # 故障现象，必填
    fault_reason: str = Field(sa_type=Text)  # 故障原因
    handling_method: str = Field(sa_type=Text)  # 处理方法




class Ticket(TicketBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # 关联关系
    histories: List["TicketHistory"] = Relationship(back_populates="ticket")

    # 关联关系
    attachments: List[Attachment] = Relationship(
        back_populates="tickets",
        link_model=TicketAttachmentLink
    )



class TicketHistory(TicketBase, table=True):
    """问题单修改记录表"""
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="ticket.id")
    changer_id: int = Field(foreign_key="user.id")  # 修改人id
    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    change_notes: str = Field(sa_type=Text, nullable=False)

    ticket: Ticket = Relationship(back_populates="histories")

