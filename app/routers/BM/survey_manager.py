import traceback

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

import qrcode
from io import BytesIO
from app.db_services.database import get_db
from app.dependencies.BM_auth import bm_verify_token
from app.logger import get_logger
from app.models import User
from app.models.survey import SurveyTable, SurveyQuestion, SurveyOption, SurveyResponse, SurveyAnswer, \
    SurveyAnswerChoice, SurveySummaryTable, SurveySummaryLinks, FactoryNoticeHistory, SurveyEvaluationAssignment
from app.schemas.survey_schema import *


router = APIRouter()
logger = get_logger('Survey_router')


# 获取某问卷所有回答列表
@router.get("/responses", response_model=ResponseList)
async def survey_responses_list(
    survey_id: int = Query(..., description="问卷 ID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    db: AsyncSession = Depends(get_db)
):
    # 1. 校验问卷是否存在
    survey_stmt = select(SurveyTable.id).where(SurveyTable.id == survey_id)
    survey_result = await db.execute(survey_stmt)
    if not survey_result.scalar():
        raise HTTPException(status_code=404, detail="Survey not found")

    # 2. 查询回答列表及其关联的答案和问题
    stmt = (
        select(SurveyResponse)
        .where(SurveyResponse.survey_id == survey_id)
        .options(
            selectinload(SurveyResponse.answers).selectinload(SurveyAnswer.question)
        )
        .order_by(SurveyResponse.id.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    responses = result.scalars().all()

    # 3. 总数统计
    count_stmt = (
        select(func.count())
        .select_from(SurveyResponse)
        .where(SurveyResponse.survey_id == survey_id)
    )
    total = (await db.execute(count_stmt)).scalar_one()

    # 4. 组装响应数据
    items = []
    for response in responses:
        metadata_answers = {
            answer.question.text: (answer.answer_text or "")
            for answer in response.answers
            if answer.question.type == "meta_data" or  answer.question.type == "target"
        }

        items.append(ResponseItem(
            id=response.id,
            submitted_at=response.submitted_at,
            metadata_answers=metadata_answers
        ))

    return ResponseList(total=total, items=items)


# 获取具体问卷回答详情
@router.get("/answer/{response_id}", response_model=ResponseDetailOut)
async def response_answer_detail(response_id: int, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    result = await db.execute(
        select(SurveyResponse)
        .where(SurveyResponse.id == response_id)
        .options(
            selectinload(SurveyResponse.survey),
            selectinload(SurveyResponse.answers)
                .selectinload(SurveyAnswer.selected_options)
                .selectinload(SurveyAnswerChoice.option),
            selectinload(SurveyResponse.answers).selectinload(SurveyAnswer.question),
            selectinload(SurveyResponse.answers)
            .selectinload(SurveyAnswer.assignments)
            .selectinload(SurveyEvaluationAssignment.evaluator)
        )
    )
    r = result.unique().scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="提交记录不存在")

    answers_out = []
    for a in r.answers:
        q = a.question

        # 初始化选项字段
        selected_option_id: Optional[int] = None
        selected_option_ids: Optional[List[int]] = None
        other_text: Optional[Dict[str, str]] = {}

        # 只处理单选、多选题的选项
        if q.type in ("single_choice", "multiple_choice") and a.selected_options:
            selected_ids = []
            for choice in a.selected_options:
                if not choice.option:
                    continue
                option_id = choice.option.id
                selected_ids.append(option_id)
                if choice.option.is_other and choice.custom_value:
                    other_text[str(option_id)] = choice.custom_value

            if q.type == "single_choice" and selected_ids:
                selected_option_id = selected_ids[0]
            elif q.type == "multiple_choice" and selected_ids:
                selected_option_ids = selected_ids

        # 清理 other_text：如果为空字典，设为 None
        if not other_text:
            other_text = None

        # 处理评价任务
        evaluations = [
            EvaluationAssignmentOut(
                id=assignment.id,
                answer_id=assignment.answer_id,
                evaluator_id=assignment.evaluator_id,
                evaluator_name=assignment.evaluator.name if assignment.evaluator else None,
                evaluation_score=assignment.evaluation_score,
                status=assignment.status,
                created_at=assignment.created_at
            )
            for assignment in a.assignments
        ]

        answers_out.append(AnswerOutFull(
            question_id=q.id,
            question_text=q.text,
            question_type=q.type,
            required=q.required,
            answer_text=a.answer_text,
            answer_rating=a.answer_rating,
            selected_option_id=selected_option_id,
            selected_option_ids=selected_option_ids,
            other_text=other_text,
            evaluations=evaluations
        ))

    return ResponseDetailOut(
        id=r.id,
        submitted_at=r.submitted_at,
        survey_title=r.survey.title if r.survey else "",
        answers=answers_out
    )



# 问卷统计
@router.get("/statistics/{survey_id}", response_model=SurveyStatisticsResponse)
async def get_survey_statistics(survey_id: int, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    survey_result = await db.execute(
        select(SurveyTable).where(SurveyTable.id == survey_id)
    )
    survey = survey_result.scalars().first()
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    questions_result = await db.execute(
        select(SurveyQuestion)
        .where(SurveyQuestion.survey_id == survey_id)
        .options(joinedload(SurveyQuestion.options))
    )
    questions = questions_result.unique().scalars().all()
    stats = []
    for q in questions:
        if q.type == "rating":
            avg_score = await db.scalar(
                select(func.avg(SurveyAnswer.answer_rating))
                .where(SurveyAnswer.question_id == q.id)
                .where(SurveyAnswer.answer_rating.is_not(None))
            )
            stats.append({
                "question_id": q.id,
                "question_text": q.text,
                "type": q.type,
                "average_score": round(float(avg_score or 0), 2)
            })
        elif q.type in ["single_choice", "multiple_choice"]:
            stmt = (
                select(SurveyOption.value, func.count(SurveyAnswerChoice.option_id))
                .join(SurveyAnswerChoice, SurveyOption.id == SurveyAnswerChoice.option_id)
                .where(SurveyOption.question_id == q.id)
                .group_by(SurveyOption.value)
            )
            result = await db.execute(stmt)
            raw_stats = result.all()
            total = sum(count for _, count in raw_stats) if raw_stats else 1
            formatted_options = [
                {
                    "option_value": value,
                    "count": count,
                    "percentage": round((count / total) * 100, 2)
                }
                for value, count in raw_stats
            ]
            stats.append({
                "question_id": q.id,
                "question_text": q.text,
                "type": q.type,
                "options_stat": formatted_options
            })
    return SurveyStatisticsResponse(root=stats)


# ———————————————— 获取所有问卷（带分页、过滤） ————————————————
@router.get("/", response_model=Dict[str, Union[int, List[SurveyOut]]])
async def list_surveys(skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    # 查询总数量
    count_stmt = select(func.count()).select_from(SurveyTable)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    result = await db.execute(select(SurveyTable).order_by(SurveyTable.id.desc()).offset(skip).limit(limit))
    surveys = result.scalars().all()

    survey_list = []
    for survey in surveys:
        survey_data = {
            "id": survey.id,
            "title": survey.title,
            "description": survey.description,
            "current_responses": survey.current_responses,
            "expire_at": survey.expire_at,
            "created_at": survey.created_at,
            "updated_at": survey.updated_at
        }
        survey_list.append(SurveyOut(**survey_data))

    return {
        "total": total,
        "items": survey_list
    }


# ———————————————— 获取单个问卷详情（含问题和选项） ————————————————
@router.get("/{survey_id}")
async def get_survey(survey_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(SurveyTable).where(SurveyTable.id == survey_id))
        survey = result.scalar_one_or_none()
        if not survey:
            raise HTTPException(status_code=404, detail="问卷不存在")
        question_result = await db.execute(select(SurveyQuestion).where(SurveyQuestion.survey_id == survey_id))
        questions = question_result.scalars().all()
        question_list = []
        for q in questions:
            option_result = await db.execute(select(SurveyOption).where(SurveyOption.question_id == q.id))
            options = option_result.scalars().all()
            question_list.append({
                "id": q.id,
                "text": q.text,
                "type": q.type,
                "required": q.required,
                "options": [
                    {
                        "id": o.id,
                        "question_id": o.question_id,
                        "value": o.value,
                        "is_other": o.is_other
                    }
                    for o in options
                ]
            })
        return {
                "id": survey.id,
                "title": survey.title,
                "require_login": survey.require_login,
                "description": survey.description,
                "created_at": survey.created_at,
                "updated_at": survey.updated_at,
                "current_responses": survey.current_responses,
                "questions": question_list
                }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="系统错误"
        )


# ———————————————— 更新问卷信息 ————————————————  这个接口没有使用
@router.put("/{survey_id}", response_model=SurveyOut)
async def update_survey(survey_id: int, survey_data: SurveyUpdate, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(SurveyTable).where(SurveyTable.id == survey_id))
        survey = result.scalar_one_or_none()
        if not survey:
            raise HTTPException(status_code=404, detail="问卷不存在")
        for key, value in survey_data.dict(exclude_unset=True).items():
            if key != 'questions':
                setattr(survey, key, value)
        await db.commit()
        await db.refresh(survey)
        survey_data = {
            "id": survey.id,
            "title": survey.title,
            "description": survey.description,
            "current_responses": survey.current_responses,
            "created_at": survey.created_at,
            "updated_at": survey.updated_at
        }
        return SurveyOut(**survey_data)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新问卷失败: {str(e)}"
        )


# ———————————————— 删除问卷 ————————————————  暂时没有使用
@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_survey(survey_id: int, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    result = await db.execute(select(SurveyTable).where(SurveyTable.id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    await db.delete(survey)
    await db.commit()
    return


# ———————————————— 生成问卷二维码 ————————————————
@router.get("/{survey_id}/qr")
async def generate_qr(request: Request, survey_id: int, token_payload: dict = Depends(bm_verify_token)):
    """
    问卷二维码
    """
    base_url = str(request.base_url)
    if "8000" in base_url:
        base_url = "http://localhost:5173/"
    url = f"{base_url}survey/fill/{survey_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return StreamingResponse(img_bytes, media_type="image/png")


@router.get("/summary/detail/{summary_id}/qr")
async def generate_qr(request: Request, summary_id: int):
    """
    汇总问卷二维码
    """
    base_url = str(request.base_url)
    if "8000" in base_url:
        base_url = "http://localhost:5173/"
    url = f"{base_url}summary/fill/{summary_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    img = qr.make_image(fill_color="black", back_color="white")
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return StreamingResponse(img_bytes, media_type="image/png")

# ———————————————— 问卷统计 ————————————————
@router.get("/{survey_id}/statistics")
async def get_survey_statistics_detail(survey_id: int, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    survey = await db.get(SurveyTable, survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    questions = await db.execute(
        select(SurveyQuestion).where(SurveyQuestion.survey_id == survey_id)
    )
    questions = questions.scalars().all()
    statistics = {
        "survey_id": survey_id,
        "title": survey.title,
        "total_responses": survey.current_responses,
        "questions": []
    }
    for question in questions:
        question_stats = {
            "question_id": question.id,
            "text": question.text,
            "type": question.type,
            "statistics": {}
        }
        if question.type in ['single_choice', 'multiple_choice']:
            options = await db.execute(
                select(SurveyOption).where(SurveyOption.question_id == question.id)
            )
            options = options.scalars().all()
            for option in options:
                count = await db.execute(
                    select(func.count(SurveyAnswerChoice.option_id))
                    .where(SurveyAnswerChoice.option_id == option.id)
                )
                count = count.scalar()
                question_stats["statistics"][option.value] = count
        elif question.type == 'rating':
            ratings = await db.execute(
                select(SurveyAnswer.answer_rating)
                .where(SurveyAnswer.question_id == question.id)
                .where(SurveyAnswer.answer_rating.isnot(None))
            )
            ratings = ratings.scalars().all()
            if ratings:
                question_stats["statistics"] = {
                    "average": sum(ratings) / len(ratings),
                    "min": min(ratings),
                    "max": max(ratings),
                    "distribution": {
                        str(i): ratings.count(i) for i in range(1, 6)
                    }
                }
        elif question.type == 'text':
            count = await db.execute(
                select(func.count(SurveyAnswer.id))
                .where(SurveyAnswer.question_id == question.id)
                .where(SurveyAnswer.answer_text.isnot(None))
            )
            question_stats["statistics"]["total_text_answers"] = count.scalar()
        statistics["questions"].append(question_stats)
    return statistics


# ———————————————— 下载问卷统计表 ————————————————
@router.get("/whf/{survey_id}/download_excel")
async def export_survey_data_excel(survey_id: int, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    survey = await db.get(SurveyTable, survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    questions_result = await db.execute(
        select(SurveyQuestion).where(SurveyQuestion.survey_id == survey_id)
    )
    questions = questions_result.scalars().all()

    responses_result = await db.execute(
        select(SurveyResponse).where(SurveyResponse.survey_id == survey_id)
    )
    responses = responses_result.scalars().all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "问卷统计"

    # 添加表头
    headers = [question.text for question in questions]
    headers.append("提交时间")
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for response in responses:
        submit_time = response.submitted_at
        row = []
        for question in questions:
            answer_result = await db.execute(
                select(SurveyAnswer)
                .where(SurveyAnswer.response_id == response.id)
                .where(SurveyAnswer.question_id == question.id)
            )
            answer = answer_result.scalars().first()

            if answer:
                if question.type == "rating":
                    row.append(str(answer.answer_rating) if answer.answer_rating is not None else "")
                elif question.type in ["single_choice", "multiple_choice"]:
                    # 这里查选项及自定义值
                    choices_result = await db.execute(
                        select(SurveyOption, SurveyAnswerChoice)
                        .join(SurveyAnswerChoice, SurveyOption.id == SurveyAnswerChoice.option_id)
                        .where(SurveyAnswerChoice.answer_id == answer.id)
                    )
                    choices_rows = choices_result.all()

                    values = []
                    for choice, answer_choice in choices_rows:
                        val = choice.value
                        # 拼接 custom_value，当 is_other 为 True 时
                        if choice.is_other and answer_choice.custom_value:
                            val += f" {answer_choice.custom_value}"
                        values.append(val)
                    row.append(", ".join(values) if values else "")
                elif question.type == "text":
                    row.append(answer.answer_text or "")
                elif question.type == "meta_data":
                    # 直接输出文本回答，或者自定义字段值
                    # 假设 meta_data 类型存放在 answer_text 中，也可根据实际调整
                    val = answer.answer_text or ""
                    # 如果有 rating 或其他类型，可以根据需要处理
                    row.append(val)
                else:
                    row.append("")
            else:
                row.append("")
        row.append(submit_time)
        ws.append(row)

    # 自动调整列宽
    for column in ws.columns:
        max_length = 0
        column_letter = openpyxl.utils.get_column_letter(column[0].column)
        for cell in column:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        adjusted_width = max_length + 2
        ws.column_dimensions[column_letter].width = adjusted_width

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=survey_{survey_id}_data.xlsx"
        }
    )


@router.get("/{survey_id}/download_excel")
async def export_survey_data_excel(survey_id: int, db: AsyncSession = Depends(get_db), token_payload: dict = Depends(bm_verify_token)):
    survey = await db.get(SurveyTable, survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 获取问题
    questions_result = await db.execute(
        select(SurveyQuestion).where(SurveyQuestion.survey_id == survey_id)
    )
    questions = questions_result.scalars().all()

    # 创建问题ID到排序序号的映射字典，而不是给对象添加属性
    question_sort_index = {}
    for index, q in enumerate(questions, start=1):
        question_sort_index[q.id] = index  # 存储每个问题ID对应的序号

    # 分离普通问题和评价问题（保持原有顺序）
    normal_questions = [q for q in questions if q.type != "evaluate"]
    evaluate_questions = [q for q in questions if q.type == "evaluate"]

    # 获取 responses
    responses_result = await db.execute(
        select(SurveyResponse).where(SurveyResponse.survey_id == survey_id)
    )
    responses = responses_result.scalars().all()

    # 检查是否有评价任务
    eval_exist_result = await db.execute(
        select(func.count(SurveyEvaluationAssignment.id))
        .join(SurveyAnswer, SurveyAnswer.id == SurveyEvaluationAssignment.answer_id)
        .where(SurveyAnswer.response_id.in_([r.id for r in responses]))
    )
    has_eval_assignments = eval_exist_result.scalar() > 0

    # 初始化 Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "问卷统计"

    # === 构建表头 ===
    headers = []
    question_to_col_index: Dict[int, int] = {}
    col_idx = 1

    if has_eval_assignments:
        headers.append("填写人")
        col_idx += 1

    # 按原始顺序（ID排序）添加所有问题的序号作为表头
    for q in questions:
        # 使用映射字典获取序号
        headers.append(str(question_sort_index[q.id]))
        question_to_col_index[q.id] = col_idx
        col_idx += 1

    headers.append("提交时间")
    submit_time_col = col_idx

    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    # === 写入数据 ===
    for response in responses:
        # 获取普通答案
        answer_result = await db.execute(
            select(SurveyAnswer).where(SurveyAnswer.response_id == response.id)
        )
        answers = {ans.question_id: ans for ans in answer_result.scalars().all()}

        if has_eval_assignments:
            # 获取评价任务 + 填写人
            eval_assignments_result = await db.execute(
                select(SurveyEvaluationAssignment, User)
                .join(User, SurveyEvaluationAssignment.evaluator_id == User.id, isouter=True)
                .join(SurveyAnswer, SurveyEvaluationAssignment.answer_id == SurveyAnswer.id)
                .where(SurveyAnswer.response_id == response.id)
            )
            eval_assignments_with_user = eval_assignments_result.all()

            # 分组评价人
            evaluators = {}
            for ea, user in eval_assignments_with_user:
                evaluator_name = user.name if user else "未知"
                if evaluator_name not in evaluators:
                    evaluators[evaluator_name] = {
                        "is_master": ea.identity == "master",
                        "assignments": []
                    }
                if not evaluators[evaluator_name]["is_master"]:
                    evaluators[evaluator_name]["is_master"] = ea.identity == "master"
                evaluators[evaluator_name]["assignments"].append(ea)

            # 确保有主评价人
            has_master = any(info["is_master"] for info in evaluators.values())
            if not has_master:
                evaluators["主评价人"] = {"is_master": True, "assignments": []}

            sorted_evaluators = sorted(
                evaluators.items(),
                key=lambda x: not x[1]["is_master"]
            )

            # 写入行
            for evaluator_name, info in sorted_evaluators:
                row = [""] * len(headers)
                row[0] = evaluator_name  # 填写人

                if info["is_master"]:
                    for q in normal_questions:
                        ans = answers.get(q.id)
                        val = ""
                        if ans:
                            if q.type == "rating":
                                val = str(ans.answer_rating or "")
                            elif q.type in ["single_choice", "multiple_choice"]:
                                choices_result = await db.execute(
                                    select(SurveyOption, SurveyAnswerChoice)
                                    .join(SurveyAnswerChoice, SurveyOption.id == SurveyAnswerChoice.option_id)
                                    .where(SurveyAnswerChoice.answer_id == ans.id)
                                )
                                choices_rows = choices_result.all()
                                values = []
                                for choice, answer_choice in choices_rows:
                                    v = choice.value
                                    if choice.is_other and answer_choice.custom_value:
                                        v += f" {answer_choice.custom_value}"
                                    values.append(v)
                                val = ", ".join(values)
                            elif q.type in ["text", "meta_data", "target"]:
                                val = ans.answer_text or ""
                        row[question_to_col_index[q.id] - 1] = val

                # 填写评价题答案
                for ea in info["assignments"]:
                    ans = await db.get(SurveyAnswer, ea.answer_id)
                    if not ans or ans.question_id not in question_to_col_index:
                        continue
                    col = question_to_col_index[ans.question_id]
                    row[col - 1] = str(ea.evaluation_score) if ea.evaluation_score is not None else ""

                row[submit_time_col - 1] = response.submitted_at
                ws.append(row)

        else:
            # 没有评价任务 -> 普通问卷
            row = [""] * len(headers)
            for q in normal_questions:
                ans = answers.get(q.id)
                val = ""
                if ans:
                    if q.type == "rating":
                        val = str(ans.answer_rating or "")
                    elif q.type in ["single_choice", "multiple_choice"]:
                        choices_result = await db.execute(
                            select(SurveyOption, SurveyAnswerChoice)
                            .join(SurveyAnswerChoice, SurveyOption.id == SurveyAnswerChoice.option_id)
                            .where(SurveyAnswerChoice.answer_id == ans.id)
                        )
                        choices_rows = choices_result.all()
                        values = []
                        for choice, answer_choice in choices_rows:
                            v = choice.value
                            if choice.is_other and answer_choice.custom_value:
                                v += f" {answer_choice.custom_value}"
                            values.append(v)
                        val = ", ".join(values)
                    elif q.type in ["text", "meta_data", "target"]:
                        val = ans.answer_text or ""
                row[question_to_col_index[q.id] - 1] = val

            row[submit_time_col - 1] = response.submitted_at
            ws.append(row)

    # 自动列宽
    for column in ws.columns:
        max_length = 0
        column_letter = get_column_letter(column[0].column)
        for cell in column:
            if cell.value:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[column_letter].width = min(max_length + 2, 50)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=survey_{survey_id}_data.xlsx"
        }
    )


# ---------------------------------------------- 汇总问卷功能 ----------------------------------------------

# 查询所有汇总问卷列表
@router.get("/survey_summary/", response_model=Dict[str, Union[int, List[SummaryOut]]])
async def survey_summary_list(skip: int = 0,limit: int = 10,db: AsyncSession = Depends(get_db)):
    # 查询总数
    count_stmt = select(func.count()).select_from(SurveySummaryTable)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # 查询分页数据
    result = await db.execute(
        select(SurveySummaryTable)
        .order_by(SurveySummaryTable.id.desc())
        .offset(skip)
        .limit(limit)
    )
    summaries = result.scalars().all()

    summary_list = []
    for summary in summaries:
        survey_ids = [str(link.survey_id) for link in summary.relations]
        survey_id_str = ",".join(survey_ids)

        summary_data = {
            "id": summary.id,
            "name": summary.name,
            "description": summary.description,
            "survey_ids": survey_id_str,
            "created_at": summary.created_at,
        }
        summary_list.append(SummaryOut(**summary_data))

    return {
        "total": total,
        "items": summary_list
    }


# 根据指定id修改汇总问卷
@router.put("/survey_summary/{id}", response_model=SummaryDetailOut)
async def update_summary(id: int,data: SummaryUpdateIn,db: AsyncSession = Depends(get_db)):
    # 查询现有记录
    result = await db.execute(
        select(SurveySummaryTable).where(SurveySummaryTable.id == id)
    )
    summary = result.scalars().first()

    if not summary:
        raise HTTPException(status_code=404, detail="未找到该汇总问卷")

    # 更新主表字段
    if data.name:
        summary.name = data.name
    if data.description is not None:
        summary.description = data.description

    # 更新关联关系（可选）
    if data.relations is not None:
        # 删除旧的关联
        await db.execute(
            delete(SurveySummaryLinks).where(SurveySummaryLinks.summary_id == id)
        )

        # 添加新的关联
        for relation in data.relations:
            db_relation = SurveySummaryLinks(
                summary_id=id,
                survey_id=relation.survey_id,
                description=relation.description
            )
            db.add(db_relation)

    await db.commit()
    await db.refresh(summary)

    # 查询更新后的完整数据
    result = await db.execute(
        select(SurveySummaryTable).where(SurveySummaryTable.id == id)
    )
    updated_summary = result.scalars().first()
    return SummaryDetailOut(
        id=updated_summary.id,
        name=updated_summary.name,
        description=updated_summary.description,
        created_at=updated_summary.created_at,
        relations=[
            SummaryRelationOut.model_validate(r) for r in updated_summary.relations
        ]
    )


# 查询指定id汇总问卷信息
@router.get("/survey_summary/{id}", response_model=SummaryDetailOut)
async def get_summary_by_id(id: int,db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SurveySummaryTable).where(SurveySummaryTable.id == id)
    )
    summary = result.scalars().first()

    if not summary:
        raise HTTPException(status_code=404, detail="未找到该汇总问卷")

    return SummaryDetailOut(
        id=summary.id,
        name=summary.name,
        description=summary.description,
        created_at=summary.created_at,
        relations=[
            SummaryRelationOut.model_validate(r) for r in summary.relations
        ]
    )


@router.post("/factory_notice/submit", summary="提交工厂须知登记")
async def submit_factory_notice(notice_data: FactoryNoticeCreate,db: AsyncSession = Depends(get_db)):
    """
    提交工厂须知登记信息，创建一条历史记录
    """
    try:
        # 创建新记录
        new_record = FactoryNoticeHistory(
            company_name=notice_data.company_name.strip(),
            contacts=notice_data.contacts.strip(),
            created_at=datetime.now()
        )

        db.add(new_record)
        await db.commit()
        await db.refresh(new_record)

        return {
            "message": "登记成功",
            "data": {
                "id": new_record.id,
                "company_name": new_record.company_name,
                "contacts": new_record.contacts,
                "created_at": new_record.created_at.isoformat()
            }
        }

    except Exception as e:
        logger.error(f"提交工厂须知登记失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"确认提交失败: {str(e)}"
        )


# 获取多人评价结果
@router.get("/response/{response_id}/evaluations", response_model=List[EvaluationAssignmentOut])
async def get_response_evaluations(response_id: int,db: AsyncSession = Depends(get_db)):
    """获取指定问卷回答记录的所有评价任务信息，包含评价者姓名"""
    # 查询指定的回答记录及其关联的答案和评价任务
    result = await db.execute(
        select(SurveyResponse)
        .where(SurveyResponse.id == response_id)
        .options(
            joinedload(SurveyResponse.answers)
            .joinedload(SurveyAnswer.assignments)
        )
    )

    response = result.unique().scalar_one_or_none()
    if not response:
        raise HTTPException(status_code=404, detail="问卷回答记录不存在")

    # 收集所有评价任务ID，用于批量查询用户
    evaluator_ids = {assignment.evaluator_id for answer in response.answers
                     for assignment in answer.assignments}

    # 批量查询所有相关用户
    user_result = await db.execute(
        select(User).where(User.id.in_(evaluator_ids))
    )
    users = {user.id: user for user in user_result.scalars().all()}

    # 处理评价任务，添加评价者姓名
    evaluations = []
    for answer in response.answers:
        for assignment in answer.assignments:

            evaluations.append(EvaluationAssignmentOut(
                id=assignment.id,
                answer_id=assignment.answer_id,
                evaluator_id=assignment.evaluator_id,
                evaluation_score=assignment.evaluation_score,
                status=assignment.status,
                created_at=assignment.created_at
            ))

    return evaluations


# 获取指定回答表的所有评价记录
@router.get("/answers/{response_id}/evaluations", response_model=list[EvaluationAssignmentOut])
async def get_answer_evaluations(
        response_id: int,
        db: AsyncSession = Depends(get_db)
):
    """
    根据问卷回答记录ID（response_id），查询该回答下所有问题的评价任务记录
    关联逻辑：SurveyResponse → 多个SurveyAnswer → 每个SurveyAnswer的SurveyEvaluationAssignment
    """
    # 1. 验证问卷回答记录（SurveyResponse）是否存在
    response_result = await db.execute(
        select(SurveyResponse)
        .where(SurveyResponse.id == response_id)
        .options(joinedload(SurveyResponse.answers))
    )
    response = response_result.scalar_one_or_none()

    if not response:
        raise HTTPException(
            status_code=404,
            detail=f"问卷回答记录（response_id: {response_id}）不存在"
        )

    # 2. 提取该回答下所有答案的ID（用于批量查询评价记录，提高效率）
    answer_ids = [answer.id for answer in response.answers]
    if not answer_ids:
        # 若该回答下无任何答案，返回空列表（避免后续查询报错）
        return []

    # 3. 查询指定答案ID对应的所有评价记录（仅返回表内指定字段）
    evaluation_result = await db.execute(
        select(
            SurveyEvaluationAssignment.id,
            SurveyEvaluationAssignment.answer_id,
            SurveyEvaluationAssignment.evaluator_id,
            SurveyEvaluationAssignment.evaluation_score,
            SurveyEvaluationAssignment.status,
            SurveyEvaluationAssignment.updated_at
        )
        .where(SurveyEvaluationAssignment.answer_id.in_(answer_ids))
        .order_by(SurveyEvaluationAssignment.created_at.desc())  # 按创建时间倒序（最新在前）
    )
    # 转换查询结果为字典列表（便于匹配 Pydantic 模型）
    evaluations = [dict(row._mapping) for row in evaluation_result.all()]

    return evaluations


# 根据survey_id和responses_id以及evaluator_id查询到该邀请人需要填写的所有问题信息
@router.get("/evaluator/questions")
async def get_evaluation_question_ids(
    survey_id: int = Query(..., description="问卷ID"),
    response_id: int = Query(..., description="答卷ID"),
    evaluator_id: int = Query(..., description="评价人ID"),
    db: AsyncSession = Depends(get_db)
):
    try:
        # 查询需要评价的问题ID
        stmt = (
            select(SurveyAnswer.question_id)
            .join(SurveyEvaluationAssignment, SurveyEvaluationAssignment.answer_id == SurveyAnswer.id)
            .join(SurveyResponse, SurveyAnswer.response_id == SurveyResponse.id)
            .where(SurveyResponse.survey_id == survey_id)
            .where(SurveyResponse.id == response_id)
            .where(SurveyEvaluationAssignment.evaluator_id == evaluator_id)
            .where(SurveyEvaluationAssignment.status == "pending")
        )
        result = await db.execute(stmt)
        question_ids = result.scalars().all()

        # 查询被评价人信息（type为target的问题及其答案）
        target_stmt = (
            select(
                SurveyQuestion.id.label("question_id"),
                SurveyQuestion.text.label("question_text"),
                SurveyAnswer.answer_text.label("target_value")
            )
            .join(SurveyAnswer, SurveyQuestion.id == SurveyAnswer.question_id)
            .where(SurveyQuestion.survey_id == survey_id)
            .where(SurveyQuestion.type == "target")
            .where(SurveyAnswer.response_id == response_id)
        )
        target_result = await db.execute(target_stmt)
        target_info = target_result.mappings().all()

        return {
            "data": {
                "question_ids": question_ids,
                "target_persons": target_info  # 被评价人信息列表
            }
        }

    except Exception as e:
        import traceback
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="系统错误"
        )


