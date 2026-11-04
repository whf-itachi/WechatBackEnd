"""出差费用的请求 / 响应模型

字段与 `Daily Report in China all_2026.xlsx` 的「Expenses」表对齐：
    Date / Project / Name / Expense / Reason / Explanation
（Reimbursement date 由财务填写，不在本系统内，故不建列）

两条与出差记录（一天一条）不同的口径：
- 同一天可以有多条记录：一天里可能有好几张发票；
- 一条记录可以跨多天：`expense_date` 是区间起始日，`expense_date_end` 是结束日，
  单日发票结束日留空。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.expense_reason import ALL_REASONS, needs_detail, reason_text

PROJECT_MAX_LEN = 50
DETAIL_MAX_LEN = 100
EXPLANATION_MAX_LEN = 500
# 单笔上限：DECIMAL(10,2) 能存 9999 万，但单张发票超过 10 万基本是录错，接口直接拦住
EXPENSE_MAX = Decimal("100000.00")


def _normalize_multiline(v: Optional[str]) -> Optional[str]:
    """统一换行、去首尾空白；空串视为未填写（None），避免库里出现 '' 与 NULL 两种空值。"""
    if v is None:
        return None
    text = str(v).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


def _normalize_single_line(v: Optional[str]) -> Optional[str]:
    """单行字段（项目、明细）：把换行压成空格，避免导出时把表格撑乱。"""
    if v is None:
        return None
    return " ".join(str(v).split()) or None


def date_text(start: date, end: Optional[date]) -> str:
    """Date 列的展示文本：单日 `2026-01-03`，跨天 `2025-12-27 ~ 2026-01-03`。

    页面、后台表格、Excel 导出共用这一个函数，避免三处各写一遍格式。
    """
    if end and end != start:
        return f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
    return f"{start:%Y-%m-%d}"


class ExpensePayload(BaseModel):
    """提交 / 修改共用的业务字段

    校验顺序与口径：
    - 报销种类必须是 `ALL_REASONS` 里的固定值，不接受自由文本；
    - 劳保用品 / 工具 / 其他 必须有明细（只写「工具」「其他」对财务没有信息量）；
    - 金额 > 0 且 ≤ 10 万，统一保留两位小数；
    - 结束日期不得早于开始日期。
    """

    expense_date: date = Field(..., description="发票产生日期；跨天费用填区间起始日")
    expense_date_end: Optional[date] = Field(
        default=None, description="跨天费用的区间结束日；单日发票不填"
    )
    project: Optional[str] = Field(
        default=None, max_length=PROJECT_MAX_LEN, description="项目，最长 50 字符，可空"
    )
    reason: str = Field(..., description="报销种类，必须是固定选项之一")
    reason_detail: Optional[str] = Field(
        default=None, max_length=DETAIL_MAX_LEN, description="劳保用品 / 工具 / 其他的明细"
    )
    expense: Decimal = Field(..., description="开支金额")
    explanation: Optional[str] = Field(
        default=None, max_length=EXPLANATION_MAX_LEN, description="该笔消费的注解，最长 500 字符"
    )

    @field_validator("project")
    @classmethod
    def _clean_project(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_single_line(v)

    @field_validator("reason")
    @classmethod
    def _check_reason(cls, v: str) -> str:
        text = str(v).strip()
        if text not in ALL_REASONS:
            raise ValueError(f"报销种类必须是：{'、'.join(ALL_REASONS)} 之一")
        return text

    @field_validator("reason_detail")
    @classmethod
    def _clean_detail(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_single_line(v)

    @field_validator("explanation")
    @classmethod
    def _clean_explanation(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_multiline(v)

    @field_validator("expense")
    @classmethod
    def _check_expense(cls, v: Decimal) -> Decimal:
        try:
            amount = Decimal(str(v)).quantize(Decimal("0.01"))
        except Exception:
            raise ValueError("金额格式不正确")
        if amount <= 0:
            raise ValueError("金额必须大于 0")
        if amount > EXPENSE_MAX:
            raise ValueError("单笔金额不能超过 100000 元，请确认是否录错")
        return amount

    @model_validator(mode="after")
    def _check_business(self):
        if self.expense_date_end and self.expense_date_end < self.expense_date:
            raise ValueError("结束日期不能早于开始日期")
        # 劳保用品 / 工具 / 其他必须写明细，否则导出成一行「工具」「其他」没有任何信息量
        if needs_detail(self.reason) and not self.reason_detail:
            raise ValueError(f"报销种类为「{self.reason}」时必须填写明细")
        return self

    @property
    def reason_text(self) -> str:
        return reason_text(self.reason, self.reason_detail)


class ExpenseCreate(ExpensePayload):
    """移动端提交一条新的费用记录"""


class ExpenseUpdate(ExpensePayload):
    """移动端修改一条已提交的记录

    与出差记录不同，这里允许改 `expense_date`：发票日期填错是常见笔误，
    且改日期不影响唯一性（一天本来就可以多条）。改了日期就重新归属结算月。
    """


class ExpenseRecordItem(BaseModel):
    id: int
    expense_date: date
    expense_date_end: Optional[date] = None
    date_text: str
    project: Optional[str] = None
    reason: str
    reason_detail: Optional[str] = None
    reason_text: str
    expense: float
    explanation: Optional[str] = None
    create_at: Optional[datetime] = None
    update_at: Optional[datetime] = None


class ExpenseCycleResponse(BaseModel):
    """移动端填写页所需的一整个周期数据"""

    cycle_key: str
    start_date: date
    end_date: date
    deadline: date
    server_date: date
    is_current: bool = Field(..., description="是否当前可填报周期")
    editable: bool = Field(..., description="当前周期是否还能继续填写")
    editable_until: date = Field(..., description="最后一个可填日期（今天与截止日取小）")
    record_count: int = Field(0, description="本周期已提交的笔数")
    filled_days: int = Field(0, description="本周期涉及的天数（去重）")
    total_expense: float = Field(0, description="本周期金额合计")
    records: List[ExpenseRecordItem] = []


class ExpenseSubmitResponse(BaseModel):
    id: int
    expense_date: date
    expense_date_end: Optional[date] = None
    date_text: str
    project: Optional[str] = None
    reason: str
    reason_detail: Optional[str] = None
    reason_text: str
    expense: float
    explanation: Optional[str] = None
    cycle_key: str
    update_at: Optional[datetime] = None
    message: str = "提交成功，本期截止前可修改"


class ExpenseAdminItem(BaseModel):
    id: int
    user_id: int
    user_name: str
    expense_date: date
    expense_date_end: Optional[date] = None
    date_text: str
    weekday: str
    project: Optional[str] = None
    reason: str
    reason_group: str
    reason_detail: Optional[str] = None
    reason_text: str
    expense: float
    explanation: Optional[str] = None
    cycle_key: str
    create_at: Optional[datetime] = None
    update_at: Optional[datetime] = None


class ReasonGroup(BaseModel):
    """下拉选项：类别 + 该类别下的具体项"""

    group: str
    items: List[str]
    detail_required: bool = Field(False, description="选中后是否必须补明细")


class ReasonOptionResponse(BaseModel):
    groups: List[ReasonGroup]
    detail_required: List[str] = Field(default_factory=list, description="必须填明细的种类")
