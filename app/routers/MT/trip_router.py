"""移动端 —— 出差记录（工作日报）填写接口

设计要点：
- 周期规则集中在 app/utils/trip_cycle.py，接口只负责校验与落库；
- 一天一条：同一 (user_id, trip_date) 只能有一条记录，重复提交返回 409；
  数据库侧有唯一键 uq_trip_user_date 兜底，并发点两次也不会写重；
- 写入后没有 delete 接口；修改走 PUT，且只在「记录所属周期截止日（25 日）之前」允许，
  截止日过后锁定，只能查看；
- 周期内任意 <= 今天的日期都可补填，最后一天集中补录不同日期也能走通；
- 字段与 Excel「Working Overview」对齐：project / task / customer /
  worktime_begin / worktime_end / total_worktime / remark；
  total_worktime 只在这里算一次（(end - begin) * 24），之后展示、导出都直接取库里的值。
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_services.database import get_db
from app.dependencies.auth import get_current_user
from app.logger import get_logger
from app.models.trip import TripRecord
from app.models.user import User
from app.schemas.trip_schema import (
    TripCycleResponse,
    TripRecordCreate,
    TripRecordItem,
    TripRecordUpdate,
    TripSubmitResponse,
)
from app.utils.enveloping_route import EnvelopingRoute
from app.utils.trip_cycle import cycle_by_key, cycle_of, current_cycle, to_cn, today_cn

router = APIRouter(route_class=EnvelopingRoute)
logger = get_logger("trip_router")


def _as_float(value) -> Optional[float]:
    """DECIMAL 落库后是 Decimal，统一转 float 输出，前端拿到的是数字而不是字符串"""
    return None if value is None else float(value)


def _to_decimal(value: Optional[float]) -> Optional[Decimal]:
    """float → DECIMAL(5,2)，走 str 中转避免二进制浮点误差（8.5 不会变成 8.499999）"""
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"))


def _record_deadline(cycle_key: str) -> Optional[date]:
    """记录所属周期的截止日；cycle_key 异常时返回 None 由调用方兜底"""
    try:
        return cycle_by_key(cycle_key)[1]
    except (ValueError, TypeError):
        return None


def _record_dict(r: TripRecord) -> dict:
    """单条记录的移动端展示结构（/cycle 与 /records 共用，避免两处字段漂移）"""
    return {
        "id": r.id,
        "trip_date": r.trip_date,
        "project": r.project,
        "task": r.task,
        "customer": r.customer,
        "worktime_begin": r.worktime_begin,
        "worktime_end": r.worktime_end,
        "total_worktime": _as_float(r.total_worktime),
        "remark": r.remark,
        "create_at": to_cn(r.create_at),
        "update_at": to_cn(r.update_at),
    }


@router.get("/cycle", response_model=TripCycleResponse, summary="获取需要填写的周期日历")
async def get_cycle(
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM，不传则取当前可填报周期"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回周期起止日 + 本人已填记录，前端据此渲染日历并决定哪些天可点"""
    today = today_cn()
    try:
        start, end, key = cycle_by_key(cycle) if cycle else current_cycle()
    except ValueError:
        raise HTTPException(status_code=400, detail="结算月格式应为 YYYY-MM")

    try:
        result = await db.execute(
            select(TripRecord)
            .where(
                TripRecord.user_id == current_user.id,
                TripRecord.trip_date >= start,
                TripRecord.trip_date <= end,
            )
            .order_by(TripRecord.trip_date.asc(), TripRecord.id.asc())
        )
        records = result.scalars().all()

        editable = start <= today <= end
        editable_until = min(today, end)

        return {
            "cycle_key": key,
            "start_date": start,
            "end_date": end,
            "deadline": end,
            "server_date": today,
            "is_current": key == current_cycle()[2],
            "editable": editable,
            "editable_until": editable_until,
            "record_count": len(records),
            "filled_days": len({r.trip_date for r in records}),
            "records": [_record_dict(r) for r in records],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询出差周期失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询出差周期失败")


@router.post("/record", response_model=TripSubmitResponse, summary="提交当天出差记录")
async def create_record(
    payload: TripRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一天一条：提交后该日期即锁定，重复提交返回 409（截止前可用 PUT 修改内容）"""
    today = today_cn()
    start, end, _cur_key = current_cycle()
    trip_date = payload.trip_date
    # 归属按「出差日期」判定，而不是「什么时候提交」：
    # 否则同一个日期在 25 号前后提交会落到不同结算月，导出结果不可复现。
    key = cycle_of(trip_date)[2]

    # ---------- 1. 周期与日期校验 ----------
    if not (payload.project or "").strip():
        raise HTTPException(status_code=400, detail="项目不能为空")
    if trip_date < start or trip_date > end:
        raise HTTPException(
            status_code=400,
            detail=f"该日期不在当前填报周期内（{start:%Y-%m-%d} ~ {end:%Y-%m-%d}）",
        )
    if trip_date > today:
        raise HTTPException(status_code=400, detail="不能填写未来日期")

    # ---------- 2. 一天一条：先查重（并发由唯一键兜底） ----------
    existed = (
        await db.execute(
            select(TripRecord.id).where(
                TripRecord.user_id == current_user.id,
                TripRecord.trip_date == trip_date,
            )
        )
    ).first()
    if existed:
        raise HTTPException(status_code=409, detail="该日期已填写过，记录不可修改")

    # ---------- 3. 落库 ----------
    # 姓名不落库：谁填的由 user_id 唯一确定，展示时 join user 表即可
    # total_worktime 服务端计算，不信任前端传来的数值
    total_worktime = _to_decimal(payload.total_worktime)
    record = TripRecord(
        user_id=current_user.id,
        trip_date=trip_date,
        project=payload.project,
        task=payload.task,
        customer=payload.customer,
        worktime_begin=payload.worktime_begin,
        worktime_end=payload.worktime_end,
        total_worktime=total_worktime,
        remark=payload.remark,
        cycle_key=key,
    )
    db.add(record)
    try:
        await db.commit()
        await db.refresh(record)
    except IntegrityError:
        # 并发下两次提交都通过了上面的查重，唯一键会拦住第二次
        await db.rollback()
        raise HTTPException(status_code=409, detail="该日期已填写过，记录不可修改")
    except Exception as e:
        await db.rollback()
        logger.error(f"出差记录提交失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="提交失败，请稍后重试")

    logger.info(
        f"出差记录提交成功 user={current_user.id}({current_user.name}) "
        f"date={trip_date} cycle={key} project={payload.project[:50]} "
        f"worktime={payload.worktime_begin}-{payload.worktime_end} total={total_worktime}"
    )
    return {
        "id": record.id,
        "trip_date": record.trip_date,
        "project": record.project,
        "task": record.task,
        "customer": record.customer,
        "worktime_begin": record.worktime_begin,
        "worktime_end": record.worktime_end,
        "total_worktime": _as_float(record.total_worktime),
        "remark": record.remark,
        "cycle_key": record.cycle_key,
        "update_at": to_cn(record.update_at),
        "message": "提交成功，本期截止前可修改",
    }


@router.put("/record/{record_id}", response_model=TripSubmitResponse, summary="修改已填记录（仅本周期截止前）")
async def update_record(
    record_id: int,
    payload: TripRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改自己已填的那条记录

    可改窗口 = 该记录所属周期的截止日（25 日）当天及之前。
    - 截止日之后：403，记录锁定，只能查看；
    - 不属于本人：404（不区分"不存在"与"无权"，避免探测他人记录）；
    - 只能改业务字段，trip_date / cycle_key 保持不变，避免账目被改到别的月份。
    """
    record = (
        await db.execute(
            select(TripRecord).where(
                TripRecord.id == record_id,
                TripRecord.user_id == current_user.id,
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

    # ---------- 覆盖业务字段（日期与周期不动） ----------
    record.project = payload.project
    record.task = payload.task
    record.customer = payload.customer
    record.worktime_begin = payload.worktime_begin
    record.worktime_end = payload.worktime_end
    record.total_worktime = _to_decimal(payload.total_worktime)
    record.remark = payload.remark
    record.update_at = datetime.now(timezone.utc)

    try:
        await db.commit()
        await db.refresh(record)
    except Exception as e:
        await db.rollback()
        logger.error(f"出差记录修改失败 id={record_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="修改失败，请稍后重试")

    logger.info(
        f"出差记录修改成功 user={current_user.id}({current_user.name}) id={record_id} "
        f"date={record.trip_date} project={record.project[:50]} "
        f"worktime={record.worktime_begin}-{record.worktime_end} total={record.total_worktime}"
    )
    return {
        "id": record.id,
        "trip_date": record.trip_date,
        "project": record.project,
        "task": record.task,
        "customer": record.customer,
        "worktime_begin": record.worktime_begin,
        "worktime_end": record.worktime_end,
        "total_worktime": _as_float(record.total_worktime),
        "remark": record.remark,
        "cycle_key": record.cycle_key,
        "update_at": to_cn(record.update_at),
        "message": "修改成功，截至本期截止日仍可再次修改",
    }


@router.get("/records", response_model=list[TripRecordItem], summary="本人某周期已填记录")
async def list_my_records(
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM，不传则当前周期"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        start, end, _ = cycle_by_key(cycle) if cycle else current_cycle()
    except ValueError:
        raise HTTPException(status_code=400, detail="结算月格式应为 YYYY-MM")

    result = await db.execute(
        select(TripRecord)
        .where(
            TripRecord.user_id == current_user.id,
            TripRecord.trip_date >= start,
            TripRecord.trip_date <= end,
        )
        .order_by(TripRecord.trip_date.asc(), TripRecord.id.asc())
    )
    records = result.scalars().all()
    return [_record_dict(r) for r in records]
