from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Column, Index, Numeric
from sqlmodel import Field, SQLModel


class ExpenseRecord(SQLModel, table=True):
    """出差费用报销记录表（对应 `Daily Report in China` 的 Expenses 表）

    与出差记录（trip_record）的关键差别：
    - **一天可以有多条**：同一天可能有多张发票（打车 + 住宿 + 工具），所以没有
      (user_id, expense_date) 唯一键，只建普通索引便于按人按天查；
    - **一条可以跨多天**：住宿、租车这类一张票覆盖几天，用 `expense_date` +
      `expense_date_end` 表示区间，单日发票 `expense_date_end` 留空；
    - 姓名不落库：填表人由 `user_id` 唯一确定，展示/导出时 join `user` 表取最新姓名，
      与 trip_record 的口径保持一致。
    """

    __tablename__ = "expense_record"
    __table_args__ = (
        Index("ix_expense_user_date", "user_id", "expense_date"),
        Index("ix_expense_date", "expense_date"),
        Index("ix_expense_cycle_key", "cycle_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", ondelete="RESTRICT", description="填写人 id")

    # ---------- 与 Expenses 表对齐的业务列 ----------
    expense_date: date = Field(description="发票产生日期（对应 Date 列）；跨天费用填区间起始日")
    expense_date_end: Optional[date] = Field(
        default=None, description="跨天费用的区间结束日；单日发票为 NULL"
    )
    project: Optional[str] = Field(
        default=None, max_length=50, description="项目（对应 Project 列，可空）"
    )
    reason: str = Field(max_length=20, description="报销种类（对应 Reason 列，固定选项之一）")
    reason_detail: Optional[str] = Field(
        default=None, max_length=100, description="劳保用品/工具/其他的开放明细，其余种类为空"
    )
    expense: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False, comment="开支金额（对应 Expense 列）"),
        description="开支金额",
    )
    explanation: Optional[str] = Field(
        default=None, max_length=500, description="该笔消费的注解（对应 Explanation 列）"
    )

    cycle_key: str = Field(max_length=7, description="归属结算月，如 2026-11")
    create_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="提交时间"
    )
    update_at: Optional[datetime] = Field(default=None, description="最后修改时间")
