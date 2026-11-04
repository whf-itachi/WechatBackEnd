"""后台管理 —— 出差费用查询 / 导出

查询口径：
- 一律按 cycle_key（结算月）过滤，边界日 25 号不会被相邻两个月重复统计；
- 明细支持按姓名、项目、报销种类、具体日期区间再过滤；报销种类按「类别」筛（交通工具等），
  这样点「交通工具」能一次看到出租车 + 火车 + 飞机，符合财务对账习惯。

导出口径（对齐 `Daily Report in China all_2026.xlsx` 的「Expenses」表）：
- 工作表名 Expenses；第 1 行 A 列写标题 Expense、D 列写金额合计（与源表同位置）；
- 第 2 行表头 6 列：A Date / B Project / C Name / D Expense / E Reason / F Explanation
  （源表最后的 Reimbursement date 由财务填写，本系统不做，故不输出）；
- 数据从第 3 行开始，按「姓名 + 日期」排序，一个人的所有票据连在一起，便于按阶段贴票；
- Date 列：单日发票写真实日期，跨天发票写 `2025-12-27 ~ 2026-01-03` 文本；
- Reason 列：劳保用品 / 工具 / 其他带明细，写成一格「工具-22mm 套筒」。
- 目前只做**全量导出**：忽略结算月与全部筛选条件，一次导出全部历史记录。
"""

import tempfile
import urllib.parse
from datetime import date, datetime
from typing import Optional

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_services.database import get_db
from app.dependencies.BM_auth import bm_verify_token
from app.logger import get_logger
from app.models.expense import ExpenseRecord
from app.models.user import User
from app.utils.enveloping_route import EnvelopingRoute
from app.utils.expense_reason import DETAIL_REQUIRED, REASON_GROUPS, REASON_TO_GROUP, reason_text
from app.utils.trip_cycle import cycle_by_key, current_cycle, recent_cycle_keys, to_cn

router = APIRouter(route_class=EnvelopingRoute)
logger = get_logger("expense_manager")

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 导出的 6 列（源表 A~F，G 列 Reimbursement date 不输出）
HEADERS = ["Date", "Project", "Name", "Expense", "Reason", "Explanation"]
# 列宽照抄源表前 6 列，贴回原表时不至于错位
COLUMN_WIDTHS = [19.33, 13.55, 14.66, 18.44, 44.0, 46.11]


def _resolve_cycle(cycle: Optional[str]) -> tuple:
    try:
        return cycle_by_key(cycle) if cycle else current_cycle()
    except ValueError:
        raise HTTPException(status_code=400, detail="结算月格式应为 YYYY-MM")


def _as_float(value) -> Optional[float]:
    """DECIMAL → float，避免 JSON 里出现字符串型数值"""
    return None if value is None else float(value)


def _date_text(r: ExpenseRecord) -> str:
    start = r.expense_date
    end = r.expense_date_end
    if end and end != start:
        return f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
    return f"{start:%Y-%m-%d}"


def _record_dict(r: ExpenseRecord, user_name: Optional[str]) -> dict:
    """后台明细行，字段与导出列一一对应"""
    return {
        "id": r.id,
        "user_id": r.user_id,
        "user_name": user_name or "（账号已删除）",
        "expense_date": r.expense_date.isoformat(),
        "expense_date_end": r.expense_date_end.isoformat() if r.expense_date_end else None,
        "date_text": _date_text(r),
        "weekday": WEEKDAY_CN[r.expense_date.weekday()],
        "project": r.project,
        "reason": r.reason,
        "reason_group": REASON_TO_GROUP.get(r.reason, "其他"),
        "reason_detail": r.reason_detail,
        "reason_text": reason_text(r.reason, r.reason_detail),
        "expense": _as_float(r.expense),
        "explanation": r.explanation,
        "cycle_key": r.cycle_key,
        "create_at": to_cn(r.create_at),
        "update_at": to_cn(r.update_at),
    }


@router.get("/reasons", summary="报销种类选项（下拉 / 筛选共用）")
async def list_reasons(token_payload: dict = Depends(bm_verify_token)):
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


@router.get("/list", summary="出差费用明细（分页）")
async def list_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM"),
    name: Optional[str] = Query(None, description="姓名模糊匹配"),
    project: Optional[str] = Query(None, description="项目模糊匹配"),
    reason_group: Optional[str] = Query(None, description="报销种类类别，如 交通工具"),
    date_from: Optional[str] = Query(None, description="票期起始日下限 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="票期起始日上限 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token),
):
    start, end, key = _resolve_cycle(cycle)
    try:
        # 姓名不落库，统一 join user 表取最新姓名
        stmt = (
            select(ExpenseRecord, User.name)
            .outerjoin(User, User.id == ExpenseRecord.user_id)
            .where(ExpenseRecord.cycle_key == key)
        )
        if name:
            stmt = stmt.where(User.name.ilike(f"%{name}%"))
        if project:
            stmt = stmt.where(ExpenseRecord.project.ilike(f"%{project}%"))
        if reason_group:
            items = next(
                (g["items"] for g in REASON_GROUPS if g["group"] == reason_group), None
            )
            if not items:
                raise HTTPException(status_code=400, detail=f"未知的报销种类类别：{reason_group}")
            stmt = stmt.where(ExpenseRecord.reason.in_(items))
        if date_from:
            stmt = stmt.where(ExpenseRecord.expense_date >= _parse_date(date_from, "起始日"))
        if date_to:
            stmt = stmt.where(ExpenseRecord.expense_date <= _parse_date(date_to, "结束日"))

        rows = (
            await db.execute(
                stmt.order_by(
                    User.name.asc(),
                    ExpenseRecord.expense_date.asc(),
                    ExpenseRecord.id.asc(),
                )
            )
        ).all()
        total = len(rows)
        total_amount = sum((float(r.expense) for r, _ in rows), 0.0)
        page_rows = rows[(page - 1) * page_size: page * page_size]

        return {
            "total": total,
            "total_amount": round(total_amount, 2),
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
        logger.error(f"查询费用明细失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="查询费用明细失败")


def _parse_date(value: str, label: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label}格式应为 YYYY-MM-DD")


def _build_workbook(rows) -> openpyxl.Workbook:
    """组装导出工作簿：单个工作表「Expenses」，与源表同版式（去掉 Reimbursement date）。

    rows: [(ExpenseRecord, user_name), ...]，已按姓名、日期排好序。
    抽成纯函数是为了不连数据库也能直接验证导出版式。
    """
    wb = openpyxl.Workbook()

    # ---------- 唯一工作表：Expenses ----------
    ws = wb.active
    ws.title = "Expenses"

    # 第 1 行：标题 + 金额合计，与源表同位置（A1 / D1）
    first_row = 3
    total = sum((float(r.expense) for r, _ in rows), 0.0)

    ws["A1"] = "Expense"
    ws["A1"].font = Font(name="Calibri", size=14, bold=True)
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")
    ws["D1"] = round(total, 2)
    ws["D1"].font = Font(name="Calibri", size=14, bold=True)
    ws["D1"].number_format = "#,##0.00"
    ws["D1"].alignment = Alignment(horizontal="right", vertical="center")
    ws.row_dimensions[1].height = 22

    # 第 2 行表头：直接对齐源表，复制数据行可贴回总表
    header_font = Font(name="Calibri", size=12, bold=True)
    for col, title in enumerate(HEADERS, 1):
        cell = ws.cell(row=2, column=col, value=title)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[2].height = 20

    for idx, (r, user_name) in enumerate(rows):
        row = first_row + idx
        # Date 列：单日写真实日期（可排序、可筛选），跨天写区间文本（源表也是这么混排的）
        if r.expense_date_end and r.expense_date_end != r.expense_date:
            ws.cell(row=row, column=1, value=_date_text(r)).alignment = Alignment(
                horizontal="center", vertical="center"
            )
        else:
            cell = ws.cell(row=row, column=1, value=r.expense_date)
            cell.number_format = "yyyy-mm-dd"
            cell.alignment = Alignment(horizontal="center", vertical="center")

        ws.cell(row=row, column=2, value=r.project).alignment = Alignment(
            horizontal="left", vertical="center", wrap_text=True
        )
        ws.cell(row=row, column=3, value=user_name or "（账号已删除）").alignment = Alignment(
            horizontal="center", vertical="center"
        )
        amount = ws.cell(row=row, column=4, value=_as_float(r.expense))
        amount.number_format = "#,##0.00"
        amount.alignment = Alignment(horizontal="right", vertical="center")
        ws.cell(row=row, column=5, value=reason_text(r.reason, r.reason_detail)).alignment = Alignment(
            horizontal="left", vertical="center", wrap_text=True
        )
        ws.cell(row=row, column=6, value=r.explanation).alignment = Alignment(
            horizontal="left", vertical="center", wrap_text=True
        )

    for col, width in enumerate(COLUMN_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(col)].width = width

    ws.freeze_panes = "A3"
    # 打印/查看时表头始终可见；列宽已定，不需要再自动换行撑高
    return wb


@router.get("/export/excel", summary="导出 Excel（Expenses 版式，全量）")
async def export_excel(
    all_data: bool = Query(True, description="默认为 true：忽略结算月与筛选，导出全部历史记录"),
    cycle: Optional[str] = Query(None, description="结算月 YYYY-MM（仅 all_data=false 时生效）"),
    name: Optional[str] = Query(None, description="仅导出指定姓名（模糊，仅 all_data=false 时生效）"),
    project: Optional[str] = Query(None, description="仅导出指定项目（模糊，仅 all_data=false 时生效）"),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token),
):
    """目前需求只做全量导出；保留 all_data=false 分支是为了将来按结算月出账时不用改接口"""
    if all_data:
        key = "全部"
        logger.info("导出出差费用 Excel：全部数据（不限结算月/姓名/项目）")
    else:
        _start, _end, key = _resolve_cycle(cycle)
        logger.info(f"导出出差费用 Excel cycle={key} name={name} project={project}")

    try:
        stmt = select(ExpenseRecord, User.name).outerjoin(User, User.id == ExpenseRecord.user_id)
        if not all_data:
            stmt = stmt.where(ExpenseRecord.cycle_key == key)
            if name:
                stmt = stmt.where(User.name.ilike(f"%{name}%"))
            if project:
                stmt = stmt.where(ExpenseRecord.project.ilike(f"%{project}%"))
        rows = (
            await db.execute(
                stmt.order_by(
                    User.name.asc(),
                    ExpenseRecord.expense_date.asc(),
                    ExpenseRecord.id.asc(),
                )
            )
        ).all()

        wb = _build_workbook(rows)

        filename = f"出差费用_{key}_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
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
        logger.error(f"导出出差费用失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")
