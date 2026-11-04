"""移动端 —— 出差费用报销填写接口

设计要点（与出差记录 trip_router 保持同一套规则，差异只在"一天可以多条"）：
- 周期规则复用 `app/utils/trip_cycle.py`：每月 25 日截止，`cycle_key` 按发票日期归属；
- **一天可以填多条**：一天里可能有好几张发票，所以没有唯一键、也不做重复提交拦截；
- **一条可以跨多天**：`expense_date` ~ `expense_date_end` 表示一张票覆盖的期间，
  单日发票结束日留空；
- 只允许填当前周期内、且不晚于今天的日期；
- 修改 / 删除只在该记录所属周期截止日（25 日）之前允许，截止后锁定为只读；
- 报销种类是固定选项（`app/utils/expense_reason.py`），服务端强校验，不接受自由文本。
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_services.database import get_db
from app.dependencies.auth import get_current_user
from app.logger import get_logger
from app.models.expense import ExpenseRecord
from app.models.user import User
from app.schemas.expense_schema import (
    ExpenseCreate,
    ExpenseCycleResponse,
    ExpenseRecordItem,
    ExpenseUpdate,
    ExpenseSubmitResponse,
    ReasonOptionResponse,
)
from app.utils.enveloping_route import EnvelopingRoute
from app.utils.expense_reason import DETAIL_REQUIRED, REASON_GROUPS, reason_text
from app.utils.trip_cycle import cycle_by_key, cycle_of, current_cycle, to_cn, today_cn

router = APIRouter(route_class=EnvelopingRoute)
logger = get_logger("expense_router")


def _as_float(value) -> Optional[float]:
    """DECIMAL 落库后是 Decimal，统一转 float 输出，前端拿到的是数字而不是字符串"""
    return None if value is None else float(value)


def _to_decimal(value) -> Decimal:
    """float/Decimal → DECIMAL(10,2)，走 str 中转避免二进制浮点误差（38.66 不会变成 38.659999）"""
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _date_text(r: ExpenseRecord) -> str:
    start = r.expense_date
    end = r.expense_date_end
    if end and end != start:
        return f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
    return f"{start:%Y-%m-%d}"


def _record_dict(r: ExpenseRecord) -> dict:
    """单条记录的移动端展示结构（/cycle 与 /records 共用，避免两处字段漂移）"""
    return {
        "id": r.id,
        "expense_date": r.expense_date,
        "expense_date_end": r.expense_date_end,
        "date_text": _date_text(r),
        "project": r.project,
        "reason": r.reason,
        "reason_detail": r.reason_detail,
        "reason_text": reason_text(r.reason, r.reason_detail),
        "expense": _as_float(_to_decimal(r.expense)),
        "explanation": r.explanation,
        "create_at": to_cn(r.create_at),
        "update_at": to_cn(r.update_at),
    }


def _record_deadline(cycle_key: str) -> Optional[date]:
    """记录所属周期的截止日；cycle_key 异常时返回 None 由调用方兜底"""
    try:
        return cycle_by_key(cycle_key)[1]
    except (ValueError, TypeError):
        return None


def _check_date_window(start: date, end: Optional[date]) -> None:
    """日期窗口校验：只允许当前周期内、且不晚于今天的日期。

    跨天费用两端都要落在窗口内 —— 否则一条记录会把票期写到未来，账目提前入账。
    """
    win_start, win_end, _ = current_cycle()
    today = today_cn()
    if start < win_start or start > win_end:
        raise HTTPException(
            status_code=400,
            detail=f"日期不在当前填报周期内（{win_start:%Y-%m-%d} ~ {win_end:%Y-%m-%d}）",
        )
    if start > today:
        raise HTTPException(status_code=400, detail="不能填写未来日期")
    if end:
        if end < start:
            raise HTTPException(status_code=400, detail="结束日期不能早于开始日期")
        if end > today:
            raise HTTPException(status_code=400, detail="结束日期不能晚于今天")


@router.get("/reasons", response_model=ReasonOptionResponse, summary="报销种类下拉选项（固定）")
async def list_reasons(current_user: User = Depends(get_current_user)):
    """前端下拉不硬编码，统一读这里的字典，新增种类只改后端一处"""
    return {
        "groups": [
            {
                "group": g["group"],
                "items": g["items"],
                "detail_required": g["detail_required"],
            }
            for g in REASON_GROUPS
        ],
        "detail_required": list(DETAIL_REQUIRED),
    }


@router.get("/cycle", response_model=ExpenseCycleResponse, summary="获取本期费用填写情况")
async def get_cycle(
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM，不传则取当前可填报周期"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回周期起止日 + 本人本期的费用明细与金额合计，前端据此渲染列表与合计"""
    today = today_cn()
    try:
        start, end, key = cycle_by_key(cycle) if cycle else current_cycle()
    except ValueError:
        raise HTTPException(status_code=400, detail="结算月格式应为 YYYY-MM")

    try:
        result = await db.execute(
            select(ExpenseRecord)
            .where(
                ExpenseRecord.user_id == current_user.id,
                ExpenseRecord.expense_date >= start,
                ExpenseRecord.expense_date <= end,
            )
            .order_by(ExpenseRecord.expense_date.desc(), ExpenseRecord.id.desc())
        )
        records = result.scalars().all()

        total = sum((_to_decimal(r.expense) for r in records), Decimal("0.00"))
        editable = start <= today <= end

        return {
            "cycle_key": key,
            "start_date": start,
            "end_date": end,
            "deadline": end,
            "server_date": today,
            "is_current": key == current_cycle()[2],
            "editable": editable,
            "editable_until": min(today, end),
            "record_count": len(records),
            "filled_days": len({r.expense_date for r in records}),
            "total_expense": float(total),
            "records": [_record_dict(r) for r in records],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询费用周期失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询费用周期失败")


@router.post("/record", response_model=ExpenseSubmitResponse, summary="提交一笔费用")
async def create_record(
    payload: ExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一天可以提交多笔；归属结算月按发票日期（起始日）判定，不按提交时间"""
    _check_date_window(payload.expense_date, payload.expense_date_end)
    key = cycle_of(payload.expense_date)[2]

    record = ExpenseRecord(
        user_id=current_user.id,
        expense_date=payload.expense_date,
        expense_date_end=payload.expense_date_end,
        project=payload.project,
        reason=payload.reason,
        reason_detail=payload.reason_detail,
        expense=_to_decimal(payload.expense),
        explanation=payload.explanation,
        cycle_key=key,
    )
    db.add(record)
    try:
        await db.commit()
        await db.refresh(record)
    except Exception as e:
        await db.rollback()
        logger.error(f"费用记录提交失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="提交失败，请稍后重试")

    logger.info(
        f"费用记录提交成功 user={current_user.id}({current_user.name}) id={record.id} "
        f"date={_date_text(record)} cycle={key} reason={record.reason} "
        f"amount={record.expense} project={(record.project or '')[:50]}"
    )
    data = _record_dict(record)
    data["cycle_key"] = record.cycle_key
    data["message"] = "提交成功，本期截止前可修改"
    return data


@router.put("/record/{record_id}", response_model=ExpenseSubmitResponse, summary="修改本人一条费用")
async def update_record(
    record_id: int,
    payload: ExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """可改窗口 = 该记录所属周期的截止日（25 日）当天及之前；过期 403，非本人 404

    与出差记录不同，这里允许改 `expense_date`（发票日期填错是常见笔误），
    改了日期就按新日期重新归属结算月。
    """
    record = (
        await db.execute(
            select(ExpenseRecord).where(
                ExpenseRecord.id == record_id,
                ExpenseRecord.user_id == current_user.id,
            )
        )
    ).scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    deadline = _record_deadline(record.cycle_key)
    if deadline is None:
        logger.error(f"记录周期异常 id={record_id} cycle_key={record.cycle_key!r}")
        raise HTTPException(status_code=500, detail="记录所属周期异常，请联系管理员")
    if today_cn() > deadline:
        raise HTTPException(
            status_code=403,
            detail=f"该记录所属周期已于 {deadline:%Y-%m-%d} 截止，不可修改",
        )

    _check_date_window(payload.expense_date, payload.expense_date_end)

    record.expense_date = payload.expense_date
    record.expense_date_end = payload.expense_date_end
    record.project = payload.project
    record.reason = payload.reason
    record.reason_detail = payload.reason_detail
    record.expense = _to_decimal(payload.expense)
    record.explanation = payload.explanation
    record.cycle_key = cycle_of(payload.expense_date)[2]
    record.update_at = datetime.now(timezone.utc)

    try:
        await db.commit()
        await db.refresh(record)
    except Exception as e:
        await db.rollback()
        logger.error(f"费用记录修改失败 id={record_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="修改失败，请稍后重试")

    logger.info(
        f"费用记录修改成功 user={current_user.id}({current_user.name}) id={record_id} "
        f"date={_date_text(record)} reason={record.reason} amount={record.expense}"
    )
    data = _record_dict(record)
    data["cycle_key"] = record.cycle_key
    data["message"] = "修改成功，截至本期截止日仍可再次修改"
    return data


@router.delete("/record/{record_id}", summary="删除本人一条费用（仅本周期截止前）")
async def delete_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """录错了要能删。窗口与修改一致：所属周期截止日之后不再允许，避免已报销的账被动过。"""
    record = (
        await db.execute(
            select(ExpenseRecord).where(
                ExpenseRecord.id == record_id,
                ExpenseRecord.user_id == current_user.id,
            )
        )
    ).scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    deadline = _record_deadline(record.cycle_key)
    if deadline is None:
        raise HTTPException(status_code=500, detail="记录所属周期异常，请联系管理员")
    if today_cn() > deadline:
        raise HTTPException(
            status_code=403,
            detail=f"该记录所属周期已于 {deadline:%Y-%m-%d} 截止，不可删除",
        )

    snapshot = f"date={_date_text(record)} reason={record.reason} amount={record.expense}"
    try:
        await db.delete(record)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"费用记录删除失败 id={record_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="删除失败，请稍后重试")

    logger.info(f"费用记录删除成功 user={current_user.id}({current_user.name}) id={record_id} {snapshot}")
    return {"id": record_id, "message": "已删除"}


@router.get("/records", response_model=list[ExpenseRecordItem], summary="本人某周期的费用明细")
async def list_my_records(
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM，不传则当前周期"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        start, end, _ = cycle_by_key(cycle) if cycle else current_cycle()
    except ValueError:
        raise HTTPException(status_code=400, detail="结算月格式应为 YYYY-MM")

    records = (
        await db.execute(
            select(ExpenseRecord)
            .where(
                ExpenseRecord.user_id == current_user.id,
                ExpenseRecord.expense_date >= start,
                ExpenseRecord.expense_date <= end,
            )
            .order_by(ExpenseRecord.expense_date.desc(), ExpenseRecord.id.desc())
        )
    ).scalars().all()
    return [_record_dict(r) for r in records]
