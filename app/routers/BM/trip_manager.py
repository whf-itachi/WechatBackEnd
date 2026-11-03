"""后台管理 —— 出差记录（工作日报）查询 / 导出

查询口径：
- 一律按 cycle_key（结算月）过滤，边界日 25 号不会被相邻两个月重复统计；
- 明细支持按姓名、项目、具体日期再过滤；
- 导出工作表与 `Daily Report in China all_2026.xlsx` 的「Working Overview」对齐（原表的
  Waiting time 列不再输出，导出为 A~I 九列）：
  A Date / B Project / C Task / D Customer / E Name /
  F Worktime Begin / G Worktime End / H Total Worktime / I 备注。
- 导出支持 `all_data=true`：忽略结算月与筛选条件，一次导出全部历史记录。
"""

import tempfile
import urllib.parse
from datetime import datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
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


def _build_workbook(rows) -> openpyxl.Workbook:
    """组装导出工作簿：单个工作表，与原表「Working Overview」同版式。

    rows: [(TripRecord, user_name), ...]，已按日期、姓名排好序。
    抽成纯函数是为了不连数据库也能直接验证导出版式。
    """
    wb = openpyxl.Workbook()

    # ---------- 唯一工作表：Working Overview ----------
    ws = wb.active
    ws.title = "Working Overview"

    ws["A1"] = "Daily Report Technician China"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells("A1:I1")
    ws.row_dimensions[1].height = 28

    # 表头放在第 4 行，与原表一致：复制数据行即可直接贴回总表
    # 原表的 Waiting time（等待时间）列不再输出，故这里只有 A~I 九列
    headers = [
        "Date", "Project", "Task", "Customer", "Name",
        "Worktime Begin", "Worktime End", "Total Worktime", "备注",
    ]
    # 表头用加粗黑体区分，不加底色填充
    header_font = Font(name="黑体", size=11, bold=True)
    for col, title in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=title)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

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
        ws.cell(row=row, column=9, value=r.remark)

    # 列宽照抄原表（去掉 Waiting time 后依次顺延），贴回时不至于错位
    for col, width in enumerate([11, 12.33, 58, 24.33, 22.78, 19.78, 18.11, 19.33, 20], 1):
        ws.column_dimensions[get_column_letter(col)].width = width

    # 数据行统一左对齐：日期、时间、时长默认是右对齐，和文本混排会参差不齐
    # C（Task）、I（备注）是长文本，额外自动换行；所有单元格顶端对齐
    if rows:
        for row in ws.iter_rows(min_row=5, max_row=4 + len(rows)):
            for cell in row:
                cell.alignment = Alignment(
                    horizontal="left", vertical="top", wrap_text=cell.column in (3, 9)
                )

    # 有内容的区域统一加细边框：标题行、空行、表头、数据行一个整框（与原表一致）
    for row in ws.iter_rows(min_row=1, max_row=4 + len(rows), max_col=9):
        for cell in row:
            cell.border = THIN_BORDER
    ws.freeze_panes = "A5"

    return wb


@router.get("/export/excel", summary="导出 Excel（Working Overview 版式）")
async def export_excel(
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM"),
    name: Optional[str] = Query(None, description="仅导出指定姓名（模糊）"),
    project: Optional[str] = Query(None, description="仅导出指定项目（模糊）"),
    all_data: bool = Query(False, description="true 时忽略结算月与筛选条件，导出全部历史记录"),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token),
):
    # all_data 时不做周期解析，否则 cycle 为空会退化成「当前结算月」
    if all_data:
        key = "全部"
        logger.info("导出出差记录 Excel：全部数据（不限结算月/姓名/项目）")
    else:
        start, end, key = _resolve_cycle(cycle)
        logger.info(f"导出出差记录 Excel cycle={key} name={name} project={project}")

    try:
        stmt = select(TripRecord, User.name).outerjoin(User, User.id == TripRecord.user_id)
        if not all_data:
            stmt = stmt.where(TripRecord.cycle_key == key)
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
