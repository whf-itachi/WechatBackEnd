from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class TripRecordCreate(BaseModel):
    """移动端提交一条出差记录"""

    trip_date: date = Field(..., description="出差日期，YYYY-MM-DD")
    trip_reason: str = Field(..., min_length=1, max_length=1000, description="出差原因/工作内容，自由文本")

    @field_validator("trip_reason")
    @classmethod
    def _clean_reason(cls, v: str) -> str:
        # 只做换行规范与首尾空白清理，内容本身不限制（保持"想写什么写什么"）
        text = str(v).replace("\r\n", "\n").replace("\r", "\n").strip()
        return text


class TripRecordItem(BaseModel):
    id: int
    trip_date: date
    trip_reason: str
    create_at: Optional[datetime] = None


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
    trip_reason: str
    cycle_key: str
    message: str = "提交成功，该记录不可修改"


class TripAdminItem(BaseModel):
    id: int
    user_id: int
    user_name: str
    trip_date: date
    weekday: str
    trip_reason: str
    cycle_key: str
    create_at: Optional[datetime] = None


class TripUserSummary(BaseModel):
    user_id: int
    user_name: str
    filled_days: int = Field(0, description="已填天数（去重）")
    record_count: int = Field(0, description="记录条数（一天一条）")
    dates: List[str] = Field(default_factory=list, description="已填日期，升序")
    last_submit: Optional[datetime] = None


class TripSummaryResponse(BaseModel):
    cycle_key: str
    start_date: date
    end_date: date
    total_records: int
    total_users: int = Field(..., description="参与填写的账号数")
    unfilled_users: List[str] = Field(default_factory=list, description="周期内一条都没填的启用账号")
    items: List[TripUserSummary] = []
