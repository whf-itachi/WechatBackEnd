from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Index
from sqlmodel import SQLModel, Field


class TripRecord(SQLModel, table=True):
    """出差记录表

    字段取舍：
    - user_id：谁填的，唯一身份来源（只能填自己的，写入时取登录态，前端传不进来）；
    - trip_date：出差日期，即用户在日历上点选的那一天 —— 与「什么时候录入」无关，
      月末集中补填时两者会大面积分离，因此不能用 create_at 代替；
    - cycle_key：结算月快照（由 trip_date 推导），保留是为了"已封账数据不被规则变更改写"；
    - 姓名不落库，导出/展示时 join `user` 表取最新姓名（`user.name` 唯一）。

    业务约束（接口 + 唯一键双重强制）：
    1. 一天一条：唯一键 (user_id, trip_date)，同一日期重复提交被拒（409）；
    2. 记录写入后不可修改、不可删除（没有 update/delete 接口），
       已填写的日期再点开只能查看；
    3. trip_reason 是自由文本，用户自己决定怎么写，系统只负责记录；
    4. cycle_key 按出差日期归属（25 日及以后归下一个结算月），
       同一日期永远落在同一结算月，后台按此归集，边界日不会被两个月重复统计。
    """

    __tablename__ = "trip_record"
    __table_args__ = (
        # 一天一条：唯一约束同时充当 (user_id, trip_date) 查询索引与外键所需索引
        Index("uq_trip_user_date", "user_id", "trip_date", unique=True),
        Index("ix_trip_cycle_key", "cycle_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # 与数据库一致用 RESTRICT：用户删除走软删除，物理删用户时应直接失败，
    # 而不是静默级联抹掉历史账目
    user_id: int = Field(foreign_key="user.id", ondelete="RESTRICT", description="填写人id")
    trip_date: date = Field(index=True, description="出差日期")
    trip_reason: str = Field(max_length=1000, description="出差原因")
    cycle_key: str = Field(max_length=7, description="归属结算月，如 2026-11")
    create_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="提交时间")
