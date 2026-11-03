from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Index, Numeric
from sqlmodel import SQLModel, Field


class TripRecord(SQLModel, table=True):
    """出差记录表（工作日报）"""

    __tablename__ = "trip_record"
    __table_args__ = (
        Index("uq_trip_user_date", "user_id", "trip_date", unique=True),
        Index("ix_trip_cycle_key", "cycle_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="RESTRICT", description="填写人id")
    trip_date: date = Field(index=True, description="出差日期")

    # ---------- 与 Working Overview 对齐的业务列 ----------
    project: str = Field(max_length=50, description="项目名称（对应 Project 列）")
    task: Optional[str] = Field(default=None, max_length=500, description="当天工作具体内容（Task 列）")
    customer: Optional[str] = Field(default=None, max_length=100, description="客户名称（Customer 列）")
    worktime_begin: Optional[time] = Field(default=None, description="当天工作开始时间")
    worktime_end: Optional[time] = Field(default=None, description="当天工作结束时间")
    total_worktime: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(5, 2), nullable=True, comment="当天工作总时长（小时）"),
    )
    remark: Optional[str] = Field(default=None, max_length=500, description="当天备注（备注列）")

    cycle_key: str = Field(max_length=7, description="归属结算月，如 2026-11")
    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="提交时间")
    update_at: Optional[datetime] = Field(default=None, description="最后修改时间")
