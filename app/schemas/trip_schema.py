"""出差记录（工作日报）的请求 / 响应模型

字段与 Excel「Working Overview」表对齐：
    Project / Task / Customer / Worktime Begin / Worktime End / Total Worktime / 备注

总时长口径：沿用 Excel 公式 =(G-F)*24，即（结束 - 开始）× 24 小时。
结束时间不得早于开始时间（跨零点班次不支持，接口直接拒绝），
计算只在服务端做一次，前端只负责展示，保证导出与页面一致。
"""

from datetime import date, datetime, time
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

PROJECT_MAX_LEN = 50
TASK_MAX_LEN = 500
CUSTOMER_MAX_LEN = 100
REMARK_MAX_LEN = 500


def calc_total_worktime(begin: Optional[time], end: Optional[time]) -> Optional[float]:
    """(结束 - 开始) * 24，保留两位小数；缺任一端返回 None。

    接口层已禁止「结束早于开始」，正常提交不会走到跨零点的补 24h 分支；
    保留它是为了兼容历史数据（后端改规则之前写入的跨零点记录）。
    """
    if begin is None or end is None:
        return None
    minutes = (end.hour * 60 + end.minute) - (begin.hour * 60 + begin.minute)
    if minutes < 0:
        minutes += 24 * 60
    return round(minutes / 60, 2)


def _normalize_multiline(v: Optional[str]) -> Optional[str]:
    """统一换行、去首尾空白；空串视为未填写（None），避免库里出现 '' 与 NULL 两种空值。"""
    if v is None:
        return None
    text = str(v).replace("\r\n", "\n").replace("\r", "\n").strip()
    return text or None


class TripRecordPayload(BaseModel):
    """提交 / 修改共用的业务字段（修改时不允许改 trip_date，故不放在基类）

    - 校验顺序与口径统一：项目必填且 ≤50，task/remark ≤500，customer ≤100；
    - 开始、结束必须成对出现，总时长由 calc_total_worktime 统一计算。
    """

    project: str = Field(
        ..., min_length=1, max_length=PROJECT_MAX_LEN, description="项目名称，最长 50 字符"
    )
    task: Optional[str] = Field(
        default=None, max_length=TASK_MAX_LEN, description="当天工作具体内容，最长 500 字符"
    )
    customer: Optional[str] = Field(
        default=None, max_length=CUSTOMER_MAX_LEN, description="客户名称，最长 100 字符"
    )
    worktime_begin: Optional[time] = Field(default=None, description="工作开始时间，HH:MM")
    worktime_end: Optional[time] = Field(default=None, description="工作结束时间，HH:MM")
    remark: Optional[str] = Field(
        default=None, max_length=REMARK_MAX_LEN, description="当天备注，最长 500 字符"
    )

    @field_validator("project")
    @classmethod
    def _clean_project(cls, v: str) -> str:
        text = str(v).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            raise ValueError("项目不能为空")
        return text

    @field_validator("task", "remark")
    @classmethod
    def _clean_text(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_multiline(v)

    @field_validator("customer")
    @classmethod
    def _clean_customer(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        # 客户名称按单行处理，避免导出时把表格撑乱
        return " ".join(str(v).split()) or None

    @model_validator(mode="after")
    def _check_worktime(self):
        # 开始、结束必须成对出现，否则算不出总时长
        if (self.worktime_begin is None) != (self.worktime_end is None):
            raise ValueError("工作开始时间与结束时间需要同时填写")
        # 结束不能早于开始：业务上不再接受跨零点班次（如 18:00 → 02:00），
        # 前端滚轮已按此约束限制可选范围，这里兜住直接调接口的情况。
        if self.worktime_begin and self.worktime_end and self.worktime_end < self.worktime_begin:
            raise ValueError("结束时间不能早于开始时间")
        return self

    @property
    def total_worktime(self) -> Optional[float]:
        return calc_total_worktime(self.worktime_begin, self.worktime_end)


class TripRecordCreate(TripRecordPayload):
    """移动端提交一条新的出差记录"""

    trip_date: date = Field(..., description="出差日期，YYYY-MM-DD")


class TripRecordUpdate(TripRecordPayload):
    """移动端修改一条已提交的记录

    只改业务字段，不允许改 trip_date / cycle_key：
    日期是这条记录的归属依据，改了等于换一天，应走新提交。
    """


class TripRecordItem(BaseModel):
    id: int
    trip_date: date
    project: str
    task: Optional[str] = None
    customer: Optional[str] = None
    worktime_begin: Optional[time] = None
    worktime_end: Optional[time] = None
    total_worktime: Optional[float] = None
    remark: Optional[str] = None
    create_at: Optional[datetime] = None
    update_at: Optional[datetime] = Field(None, description="最后修改时间，未改过为 null")


class TripCycleResponse(BaseModel):
    """移动端日历所需的一整个周期数据"""

    cycle_key: str
    start_date: date
    end_date: date
    deadline: date
    server_date: date
    is_current: bool = Field(..., description="是否当前可填报周期")
    editable: bool = Field(..., description="当前周期是否还能继续填写")
    editable_until: date = Field(..., description="最后一个可填日期（今天与截止日取小）")
    record_count: int = Field(0, description="本周期已提交的记录条数（一天一条，与已填天数一致）")
    filled_days: int = Field(0, description="本周期已填的天数（去重）")
    records: List[TripRecordItem] = []


class TripSubmitResponse(BaseModel):
    id: int
    trip_date: date
    project: str
    task: Optional[str] = None
    customer: Optional[str] = None
    worktime_begin: Optional[time] = None
    worktime_end: Optional[time] = None
    total_worktime: Optional[float] = None
    remark: Optional[str] = None
    cycle_key: str
    update_at: Optional[datetime] = Field(None, description="最后修改时间，未改过为 null")
    message: str = "提交成功，本期截止前可修改"


class TripAdminItem(BaseModel):
    id: int
    user_id: int
    user_name: str
    trip_date: date
    weekday: str
    project: str
    task: Optional[str] = None
    customer: Optional[str] = None
    worktime_begin: Optional[time] = None
    worktime_end: Optional[time] = None
    total_worktime: Optional[float] = None
    remark: Optional[str] = None
    cycle_key: str
    create_at: Optional[datetime] = None
    update_at: Optional[datetime] = None


class TripUserSummary(BaseModel):
    user_id: int
    user_name: str
    filled_days: int = Field(0, description="已填天数（去重）")
    record_count: int = Field(0, description="记录条数（一天一条）")
    total_worktime: float = Field(0, description="本周期填写的总时长合计（小时）")
    dates: List[str] = Field(default_factory=list, description="已填日期，升序")
    last_submit: Optional[datetime] = None


class TripSummaryResponse(BaseModel):
    cycle_key: str
    start_date: date
    end_date: date
    total_records: int
    total_users: int = Field(..., description="参与填写的账号数")
    total_worktime: float = Field(0, description="本周期所有人时长合计（小时）")
    unfilled_users: List[str] = Field(default_factory=list, description="周期内一条都没填的启用账号")
    items: List[TripUserSummary] = []
