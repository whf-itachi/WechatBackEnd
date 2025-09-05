import traceback
from datetime import timezone

import openpyxl
from openpyxl.styles import Font
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

import qrcode
from io import BytesIO
from app.db_services.database import get_db
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
            if answer.question.type == "meta_data"
        }

        items.append(ResponseItem(
            id=response.id,
            submitted_at=response.submitted_at,
            metadata_answers=metadata_answers
        ))

    return ResponseList(total=total, items=items)


# 获取具体问卷回答详情
@router.get("/answer/{response_id}", response_model=ResponseDetailOut)
async def response_answer_detail(response_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SurveyResponse)
        .where(SurveyResponse.id == response_id)
        .options(
            joinedload(SurveyResponse.survey),
            joinedload(SurveyResponse.answers)
                .joinedload(SurveyAnswer.selected_options)
                .joinedload(SurveyAnswerChoice.option),
            joinedload(SurveyResponse.answers).joinedload(SurveyAnswer.question),
            # 添加评价任务的关联加载
            joinedload(SurveyResponse.answers)
                .joinedload(SurveyAnswer.assignments)
        )
    )
    r = result.unique().scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="提交记录不存在")

    answers_out = []
    for a in r.answers:
        q = a.question

        selected_option_id = None
        selected_option_ids = None
        other_text = {}

        if a.selected_options:
            selected_ids = []
            for choice in a.selected_options:
                if not choice.option:
                    continue
                selected_ids.append(choice.option.id)
                if choice.option.is_other:
                    other_text[str(choice.option.id)] = choice.custom_value

            if q.type == "single_choice":
                selected_option_id = selected_ids[0] if selected_ids else None
            elif q.type == "multiple_choice":
                selected_option_ids = selected_ids

        # 处理评价任务信息
        evaluations = []
        if a.assignments:
            evaluations = [
                EvaluationAssignmentOut(
                    id=assignment.id,
                    answer_id=assignment.answer_id,
                    evaluator_name=assignment.evaluator_name,
                    evaluator_id=assignment.evaluator_id,
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
            other_text=other_text or None,
            evaluations=evaluations  # 添加评价信息
        ))

    return ResponseDetailOut(
        id=r.id,
        submitted_at=r.submitted_at,
        survey_title=r.survey.title if r.survey else "",
        answers=answers_out
    )


# 问卷统计
@router.get("/statistics/{survey_id}", response_model=SurveyStatisticsResponse)
async def get_survey_statistics(survey_id: int, db: AsyncSession = Depends(get_db)):
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
async def list_surveys(skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_db)):
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
        print(traceback.format_exc())
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
async def delete_survey(survey_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SurveyTable).where(SurveyTable.id == survey_id))
    survey = result.scalar_one_or_none()
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")
    await db.delete(survey)
    await db.commit()
    return


# ———————————————— 生成问卷二维码 ————————————————
@router.get("/{survey_id}/qr")
async def generate_qr(request: Request, survey_id: int):
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
async def get_survey_statistics_detail(survey_id: int, db: AsyncSession = Depends(get_db)):
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
@router.get("/{survey_id}/download_excel")
async def export_survey_data_excel(survey_id: int, db: AsyncSession = Depends(get_db)):
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
        print("--------------<>")
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
            # 获取评价者姓名，如果用户不存在则显示"未知用户"
            evaluator_name = users.get(assignment.evaluator_id, None)
            evaluator_name = evaluator_name.name if evaluator_name else "未知用户"

            evaluations.append(EvaluationAssignmentOut(
                id=assignment.id,
                answer_id=assignment.answer_id,
                evaluator_id=assignment.evaluator_id,
                evaluator_name=evaluator_name,  # 添加评价者姓名
                evaluation_score=assignment.evaluation_score,
                status=assignment.status,
                created_at=assignment.created_at
            ))

    return evaluations


# ------------------------------------------------ 绩效评价 ---------------------------------

# 获取指定答案的所有评价记录
@router.get("/answers/{answer_id}/evaluations", response_model=list[EvaluationAssignmentOut])
async def get_answer_evaluations(
        answer_id: int,
        db: AsyncSession = Depends(get_db)
):
    # 验证答案是否存在
    answer_result = await db.execute(
        select(SurveyAnswer).where(SurveyAnswer.id == answer_id)
    )
    if not answer_result.scalar_one_or_none():
        raise HTTPException(
            status_code=404,
            detail=f"答案ID {answer_id} 不存在"
        )

    # 查询该答案的所有评价记录
    result = await db.execute(
        select(SurveyEvaluationAssignment)
        .where(SurveyEvaluationAssignment.answer_id == answer_id)
        .order_by(SurveyEvaluationAssignment.created_at.desc())
    )

    return result.scalars().all()
