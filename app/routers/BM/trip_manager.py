"""后台管理 —— 出差记录（工作日报）查询 / 汇总 / 导出

查询口径：
- 一律按 cycle_key（结算月）过滤，边界日 25 号不会被相邻两个月重复统计；
- 明细支持按姓名、项目、具体日期再过滤；
- 汇总给出「每个人填了几条、几天、时长合计 + 具体日期 + 最后提交时间」，并列出周期内一条都没填的账号；
- 导出工作表与 `Daily Report in China all_2026.xlsx` 的「Working Overview」逐列对齐：
  A Date / B Project / C Task / D Customer / E Name /
  F Worktime Begin / G Worktime End / H Total Worktime / I Waiting time / J 备注。
  Waiting time（等待时间）本期不在小程序里采集，保留空列只是为了贴回原表时不串列。
"""

import tempfile
import urllib.parse
from datetime import datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_services.database import get_db
from app.dependencies.BM_auth import bm_verify_token
from app.logger import get_logger
from app.models.trip import TripRecord
from app.models.user import User
from app.utils.enveloping_route import EnvelopingRoute
from app.utils.trip_cycle import cycle_by_key, current_cycle, recent_cycle_keys, to_cn

router = APIRouter(route_class=EnvelopingRoute)
logger = get_logger("trip_manager")

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 导出版式的细边框（与原表一致，四边同线型）
_THIN = Side(style="thin")
THIN_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _resolve_cycle(cycle: Optional[str]) -> tuple:
    try:
        return cycle_by_key(cycle) if cycle else current_cycle()
    except ValueError:
        raise HTTPException(status_code=400, detail="结算月格式应为 YYYY-MM")


def _as_float(value) -> Optional[float]:
    """DECIMAL → float，避免 JSON 里出现字符串型数值"""
    return None if value is None else float(value)


def _record_dict(r: TripRecord, user_name: Optional[str]) -> dict:
    """后台明细行，字段与导出列一一对应"""
    return {
        "id": r.id,
        "user_id": r.user_id,
        "user_name": user_name or "（账号已删除）",
        "trip_date": r.trip_date.isoformat(),
        "weekday": WEEKDAY_CN[r.trip_date.weekday()],
        "project": r.project,
        "task": r.task,
        "customer": r.customer,
        "worktime_begin": r.worktime_begin.strftime("%H:%M") if r.worktime_begin else None,
        "worktime_end": r.worktime_end.strftime("%H:%M") if r.worktime_end else None,
        "total_worktime": _as_float(r.total_worktime),
        "remark": r.remark,
        "cycle_key": r.cycle_key,
        "create_at": to_cn(r.create_at),
        "update_at": to_cn(r.update_at),
    }


@router.get("/cycles", summary="可查询的结算月列表")
async def list_cycles(token_payload: dict = Depends(bm_verify_token)):
    start, end, key = current_cycle()
    options = []
    for k in recent_cycle_keys(12):
        s, e, _ = cycle_by_key(k)
        options.append(
            {
                "cycle_key": k,
                "start_date": s.isoformat(),
                "end_date": e.isoformat(),
                "label": f"{k}（{s:%m-%d} ~ {e:%m-%d}）",
                "is_current": k == key,
            }
        )
    return {"current": key, "current_start": start, "current_end": end, "options": options}


@router.get("/list", summary="出差记录明细（分页）")
async def list_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM"),
    name: Optional[str] = Query(None, description="姓名模糊匹配"),
    project: Optional[str] = Query(None, description="项目模糊匹配"),
    trip_date: Optional[str] = Query(None, description="精确到某一天 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token),
):
    start, end, key = _resolve_cycle(cycle)
    try:
        # 姓名不落库，统一 join user 表取最新姓名
        stmt = (
            select(TripRecord, User.name)
            .outerjoin(User, User.id == TripRecord.user_id)
            .where(TripRecord.cycle_key == key)
        )
        if name:
            stmt = stmt.where(User.name.ilike(f"%{name}%"))
        if project:
            stmt = stmt.where(TripRecord.project.ilike(f"%{project}%"))
        if trip_date:
            try:
                exact = datetime.strptime(trip_date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
            stmt = stmt.where(TripRecord.trip_date == exact)

        rows = (
            await db.execute(
                stmt.order_by(
                    TripRecord.trip_date.asc(),
                    User.name.asc(),
                    TripRecord.id.asc(),
                )
            )
        ).all()
        total = len(rows)
        page_rows = rows[(page - 1) * page_size: page * page_size]

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "cycle_key": key,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "items": [_record_dict(r, user_name) for r, user_name in page_rows],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询出差明细失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询出差明细失败")


@router.get("/summary", summary="按人汇总填写情况")
async def summary_by_user(
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM"),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token),
):
    start, end, key = _resolve_cycle(cycle)
    try:
        rows = (
            await db.execute(
                select(TripRecord)
                .where(TripRecord.cycle_key == key)
                .order_by(TripRecord.trip_date.asc(), TripRecord.id.asc())
            )
        ).scalars().all()

        # 姓名一次查出来做映射，避免 N+1
        all_users = (await db.execute(select(User.id, User.name, User.is_active, User.user_type))).all()
        name_map = {uid: name for uid, name, _active, _t in all_users}

        grouped: dict = {}
        for r in rows:
            item = grouped.setdefault(
                r.user_id,
                {
                    "user_id": r.user_id,
                    "dates": set(),
                    "records": 0,
                    "total_worktime": 0.0,
                    "last_submit": None,
                },
            )
            item["dates"].add(r.trip_date)
            item["records"] += 1
            item["total_worktime"] += _as_float(r.total_worktime) or 0.0
            if r.create_at and (item["last_submit"] is None or r.create_at > item["last_submit"]):
                item["last_submit"] = r.create_at

        items = []
        for item in grouped.values():
            items.append(
                {
                    "user_id": item["user_id"],
                    "user_name": name_map.get(item["user_id"]) or "（账号已删除）",
                    "filled_days": len(item["dates"]),
                    "record_count": item["records"],
                    "total_worktime": round(item["total_worktime"], 2),
                    "dates": sorted(d.isoformat() for d in item["dates"]),
                    "last_submit": to_cn(item["last_submit"]),
                }
            )
        items.sort(key=lambda x: (-x["record_count"], x["user_name"]))

        # 周期内一条没填的启用账号（只统计普通账号，管理员不参与填报）
        filled_ids = set(grouped.keys())
        unfilled = sorted(
            name for uid, name, active, utype in all_users
            if active and utype != "admin" and uid not in filled_ids
        )

        return {
            "cycle_key": key,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_records": len(rows),
            "total_users": len(grouped),
            "total_worktime": round(sum(_as_float(r.total_worktime) or 0.0 for r in rows), 2),
            "unfilled_users": unfilled,
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询出差汇总失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询出差汇总失败")


def _build_workbook(rows) -> openpyxl.Workbook:
    """组装导出工作簿：Sheet1 与原表「Working Overview」同版式，Sheet2 为人员汇总。

    rows: [(TripRecord, user_name), ...]，已按日期、姓名排好序。
    抽成纯函数是为了不连数据库也能直接验证导出版式。
    """
    wb = openpyxl.Workbook()

    # ---------- Sheet1：Working Overview ----------
    ws = wb.active
    ws.title = "Working Overview"

    ws["A1"] = "Daily Report Technician China"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:J1")
    ws.row_dimensions[1].height = 28

    # 表头放在第 4 行，与原表一致：复制数据行即可直接贴回总表
    headers = [
        "Date", "Project", "Task", "Customer", "Name",
        "Worktime Begin", "Worktime End", "Total Worktime", "Waiting time", "备注",
    ]
    # 表头用加粗黑体区分，不加底色填充
    header_font = Font(name="黑体", size=11, bold=True)
    for col, title in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=title)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.cell(row=4, column=9).comment = Comment(
        "小程序暂未采集「等待时间」，此列保留空值以便贴回总表时不串列。", "ICS"
    )

    for idx, (r, user_name) in enumerate(rows):
        row = 5 + idx
        ws.cell(row=row, column=1, value=r.trip_date).number_format = "yyyy-mm-dd"
        ws.cell(row=row, column=2, value=r.project)
        ws.cell(row=row, column=3, value=r.task)
        ws.cell(row=row, column=4, value=r.customer)
        ws.cell(row=row, column=5, value=user_name or "（账号已删除）")
        if r.worktime_begin:
            ws.cell(row=row, column=6, value=r.worktime_begin).number_format = "hh:mm"
        if r.worktime_end:
            ws.cell(row=row, column=7, value=r.worktime_end).number_format = "hh:mm"
        if r.total_worktime is not None:
            ws.cell(row=row, column=8, value=_as_float(r.total_worktime)).number_format = "0.00"
        # I 列 Waiting time 留空
        ws.cell(row=row, column=10, value=r.remark)

    # 列宽照抄原表，贴回时不至于错位
    for col, width in enumerate([11, 12.33, 58, 24.33, 22.78, 19.78, 18.11, 19.33, 12, 20], 1):
        ws.column_dimensions[get_column_letter(col)].width = width

    # 数据行统一左对齐：日期、时间、时长默认是右对齐，和文本混排会参差不齐
    # C（Task）、J（备注）是长文本，额外自动换行；所有单元格顶端对齐
    if rows:
        for row in ws.iter_rows(min_row=5, max_row=4 + len(rows)):
            for cell in row:
                cell.alignment = Alignment(
                    horizontal="left", vertical="top", wrap_text=cell.column in (3, 10)
                )

    # 有内容的区域统一加细边框：标题行、空行、表头、数据行一个整框（与原表一致）
    for row in ws.iter_rows(min_row=1, max_row=4 + len(rows), max_col=10):
        for cell in row:
            cell.border = THIN_BORDER
    ws.freeze_panes = "A5"

    # ---------- Sheet2 人员汇总 ----------
    ws2 = wb.create_sheet("人员汇总")
    headers2 = ["姓名", "出差天数", "记录条数", "总时长（小时）", "已填日期", "最后提交时间"]
    for col, title in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=title)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    grouped: dict = {}
    for r, user_name in rows:
        item = grouped.setdefault(
            r.user_id,
            {
                "name": user_name or "（账号已删除）",
                "dates": set(),
                "records": 0,
                "hours": 0.0,
                "last": None,
            },
        )
        item["dates"].add(r.trip_date)
        item["records"] += 1
        item["hours"] += _as_float(r.total_worktime) or 0.0
        if r.create_at and (item["last"] is None or r.create_at > item["last"]):
            item["last"] = r.create_at

    for item in sorted(grouped.values(), key=lambda x: (-x["records"], x["name"])):
        ws2.append(
            [
                item["name"],
                len(item["dates"]),
                item["records"],
                round(item["hours"], 2),
                "、".join(sorted(d.isoformat() for d in item["dates"])),
                to_cn(item["last"]).strftime("%Y-%m-%d %H:%M:%S") if item["last"] else "",
            ]
        )

    for col, width in enumerate([12, 12, 12, 16, 60, 20], 1):
        ws2.column_dimensions[get_column_letter(col)].width = width

    # 汇总表数据同样左对齐
    if grouped:
        for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
            for cell in row:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    # 汇总表（表头 + 数据）也套细边框
    for row in ws2.iter_rows(min_row=1, max_row=max(1, ws2.max_row), max_col=6):
        for cell in row:
            cell.border = THIN_BORDER
    ws2.freeze_panes = "A2"

    return wb


@router.get("/export/excel", summary="按结算月导出 Excel（Working Overview 版式）")
async def export_excel(
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM"),
    name: Optional[str] = Query(None, description="仅导出指定姓名（模糊）"),
    project: Optional[str] = Query(None, description="仅导出指定项目（模糊）"),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token),
):
    start, end, key = _resolve_cycle(cycle)
    logger.info(f"导出出差记录 Excel cycle={key} name={name} project={project}")

    try:
        stmt = (
            select(TripRecord, User.name)
            .outerjoin(User, User.id == TripRecord.user_id)
            .where(TripRecord.cycle_key == key)
        )
        if name:
            stmt = stmt.where(User.name.ilike(f"%{name}%"))
        if project:
            stmt = stmt.where(TripRecord.project.ilike(f"%{project}%"))
        rows = (
            await db.execute(
                stmt.order_by(
                    TripRecord.trip_date.asc(),
                    User.name.asc(),
                    TripRecord.id.asc(),
                )
            )
        ).all()

        wb = _build_workbook(rows)

        filename = f"出差记录_{key}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            wb.save(tmp.name)
            temp_path = tmp.name

        encoded = urllib.parse.quote(filename.encode("utf-8"))
        return FileResponse(
            path=temp_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出出差记录失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")
