"""移动端 —— 出差记录填写接口

设计要点：
- 周期规则集中在 app/utils/trip_cycle.py，接口只负责校验与落库；
- 一天一条：同一 (user_id, trip_date) 只能有一条记录，重复提交返回 409；
  数据库侧有唯一键 uq_trip_user_date 兜底，并发点两次也不会写重；
- 写入后没有 update/delete 接口 → 不可修改、不可删除，已填日期只能查看；
- 周期内任意 <= 今天的日期都可补填，最后一天集中补录不同日期也能走通。
"""

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
    TripSubmitResponse,
)
from app.utils.enveloping_route import EnvelopingRoute
from app.utils.trip_cycle import cycle_by_key, cycle_of, current_cycle, to_cn, today_cn

router = APIRouter(route_class=EnvelopingRoute)
logger = get_logger("trip_router")


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
            "records": [
                {
                    "id": r.id,
                    "trip_date": r.trip_date,
                    "trip_reason": r.trip_reason,
                    "create_at": to_cn(r.create_at),
                }
                for r in records
            ],
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
    """一天一条：提交即锁定该日期，重复提交返回 409"""
    today = today_cn()
    start, end, _cur_key = current_cycle()
    trip_date = payload.trip_date
    # 归属按「出差日期」判定，而不是「什么时候提交」：
    # 否则同一个日期在 25 号前后提交会落到不同结算月，导出结果不可复现。
    key = cycle_of(trip_date)[2]

    # ---------- 1. 周期与日期校验 ----------
    if not (payload.trip_reason or "").strip():
        raise HTTPException(status_code=400, detail="出差原因不能为空")
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
    record = TripRecord(
        user_id=current_user.id,
        trip_date=trip_date,
        trip_reason=payload.trip_reason,
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
        f"date={trip_date} cycle={key} reason={payload.trip_reason[:50]}"
    )
    return {
        "id": record.id,
        "trip_date": record.trip_date,
        "trip_reason": record.trip_reason,
        "cycle_key": record.cycle_key,
        "message": "提交成功，该记录不可修改",
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
    return [
        {
            "id": r.id,
            "trip_date": r.trip_date,
            "trip_reason": r.trip_reason,
            "create_at": to_cn(r.create_at),
        }
        for r in records
    ]
