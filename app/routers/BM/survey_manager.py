from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from typing import List
import csv
from io import StringIO
import qrcode
from io import BytesIO
from app.db_services.database import get_db
from app.models.survey import (
    SurveyTable as SurveyModel,
    SurveyQuestion as QuestionModel,
    SurveyOption as OptionModel,
    SurveyResponse as ResponseModel,
    SurveyAnswer as AnswerModel,
    SurveyAnswerChoice as AnswerChoiceModel
)
from app.schemas.survey_schema import (
    SurveyCreate,
    SurveyUpdate,
    SurveyOut,
    SurveyWithQuestions,
    ResponseSubmit, SurveyResponseSummary, AnswerOutFull, ResponseDetailOut
)

router = APIRouter()


@router.get("/responses", response_model=List[SurveyResponseSummary])
async def list_all_survey_responses(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ResponseModel)
        .options(selectinload(ResponseModel.survey))
        .order_by(ResponseModel.id.desc())
    )
    responses = result.scalars().all()

    return [
        SurveyResponseSummary(
            id=r.id,
            user_name=r.user_name,
            submitted_at=r.submitted_at,
            survey_title=r.survey.title if r.survey else ""
        )
        for r in responses
    ]


# 获取具体问卷回答详情
@router.get("/responses/{response_id}", response_model=ResponseDetailOut)
async def get_response_detail(response_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ResponseModel)
        .where(ResponseModel.id == response_id)
        .options(
            joinedload(ResponseModel.survey),
            joinedload(ResponseModel.answers)
            .joinedload(AnswerModel.selected_options)
            .joinedload(AnswerChoiceModel.option),
            joinedload(ResponseModel.answers)
            .joinedload(AnswerModel.question)
        )
    )
    r = result.unique().scalar_one_or_none()

    if not r:
        raise HTTPException(status_code=404, detail="提交记录不存在")

    answers_out = []
    for a in r.answers:
        q = a.question
        answers_out.append(AnswerOutFull(
            question_id=q.id,
            question_text=q.text,
            question_type=q.type,
            required=q.required,
            answer_text=a.answer_text,
            answer_rating=a.answer_rating,
            selected_option_values=[
                c.option.value for c in a.selected_options if c.option
            ] if a.selected_options else None
        ))

    return ResponseDetailOut(
        id=r.id,
        user_name=r.user_name,
        submitted_at=r.submitted_at,
        survey_title=r.survey.title if r.survey else "",
        answers=answers_out
    )




# ———————————————— 获取所有问卷（带分页、过滤） ————————————————
@router.get("/", response_model=List[SurveyOut])
async def list_surveys(skip: int = 0,limit: int = 10,db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SurveyModel).offset(skip).limit(limit))
    surveys = result.scalars().all()

    survey_list = []
    for survey in surveys:
        # 获取问卷的响应数量
        count_result = await db.execute(select(ResponseModel).where(ResponseModel.survey_id == survey.id))
        response_count = len(count_result.scalars().all())
        
        # 构造返回数据
        survey_data = {
            "id": survey.id,
            "title": survey.title,
            "description": survey.description,
            "is_active": survey.is_active,
            "current_responses": response_count,
            "created_at": survey.created_at,
            "updated_at": survey.updated_at
        }
        survey_list.append(SurveyOut(**survey_data))

    return survey_list


# ———————————————— 创建问卷 ————————————————
@router.post("/", response_model=SurveyOut)
async def create_survey(survey_data: SurveyCreate,db: AsyncSession = Depends(get_db)):
    """创建问卷，包括问题和选项"""
    try:
        # 1. 创建问卷基本信息
        survey = SurveyModel(
            title=survey_data.title,
            description=survey_data.description,
            is_active=True,
            current_responses=0
        )
        db.add(survey)
        await db.flush()  # 获取 survey.id

        # 2. 创建问题和选项
        for question_data in survey_data.questions:
            # 创建问题
            question = QuestionModel(
                survey_id=survey.id,
                text=question_data.text,
                type=question_data.type,
                required=question_data.required,
                order=question_data.order
            )
            db.add(question)
            await db.flush()  # 获取 question.id

            # 如果是选择题，创建选项
            if question_data.type in ['single_choice', 'multiple_choice'] and question_data.options:
                for option_data in question_data.options:
                    option = OptionModel(
                        question_id=question.id,
                        value=option_data.value,
                        order=option_data.order
                    )
                    db.add(option)

        await db.commit()
        await db.refresh(survey)

        # 构造返回数据
        survey_data = {
            "id": survey.id,
            "title": survey.title,
            "description": survey.description,
            "is_active": survey.is_active,
            "current_responses": survey.current_responses,
            "created_at": survey.created_at,
            "updated_at": survey.updated_at
        }
        return SurveyOut(**survey_data)

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建问卷失败: {str(e)}"
        )


# ———————————————— 获取单个问卷详情（含问题和选项） ————————————————
@router.get("/{survey_id}", response_model=SurveyWithQuestions)
async def get_survey(survey_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SurveyModel).where(SurveyModel.id == survey_id))
    survey = result.scalar_one_or_none()

    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 查询问题
    question_result = await db.execute(select(QuestionModel).where(QuestionModel.survey_id == survey_id))
    questions = question_result.scalars().all()

    question_list = []
    for q in questions:
        option_result = await db.execute(select(OptionModel).where(OptionModel.question_id == q.id))
        options = option_result.scalars().all()

        question_list.append({
            "id": q.id,
            "text": q.text,
            "order": q.order,
            "type": q.type,
            "options": [
                {
                    "id": o.id,
                    "question_id": o.question_id,
                    "value": o.value,
                    "order": o.order,
                    "created_at": o.created_at,
                }
                for o in options
            ]
        })

    # 最终返回结构
    return {
        "id": survey.id,
        "title": survey.title,
        "description": survey.description,
        "created_at": survey.created_at,
        "updated_at": survey.updated_at,
        "is_active": survey.is_active,
        "current_responses": survey.current_responses,
        "questions": question_list
    }



# ———————————————— 更新问卷信息 ————————————————
@router.put("/{survey_id}", response_model=SurveyOut)
async def update_survey(survey_id: int,survey_data: SurveyUpdate,db: AsyncSession = Depends(get_db)):
    """更新问卷信息，包括问题和选项"""
    try:
        # 获取问卷
        result = await db.execute(select(SurveyModel).where(SurveyModel.id == survey_id))
        survey = result.scalar_one_or_none()

        if not survey:
            raise HTTPException(status_code=404, detail="问卷不存在")

        # 更新问卷基本信息
        for key, value in survey_data.dict(exclude_unset=True).items():
            if key != 'questions':  # 排除questions字段，单独处理
                setattr(survey, key, value)

        # 如果包含questions字段，更新问题和选项
        if hasattr(survey_data, 'questions') and survey_data.questions:
            # 获取现有问题
            existing_questions = await db.execute(select(QuestionModel).where(QuestionModel.survey_id == survey_id))
            existing_questions = existing_questions.scalars().all()
            existing_question_ids = {q.id for q in existing_questions}

            # 处理每个问题
            for question_data in survey_data.questions:
                if hasattr(question_data, 'id') and question_data.id:
                    # 更新现有问题
                    question = next((q for q in existing_questions if q.id == question_data.id), None)
                    if question:
                        question.text = question_data.text
                        question.type = question_data.type
                        question.required = question_data.required
                        question.order = question_data.order
                        existing_question_ids.remove(question.id)
                else:
                    # 创建新问题
                    question = QuestionModel(
                        survey_id=survey_id,
                        text=question_data.text,
                        type=question_data.type,
                        required=question_data.required,
                        order=question_data.order
                    )
                    db.add(question)
                    await db.flush()

                # 处理选项
                if question_data.type in ['single_choice', 'multiple_choice'] and question_data.options:
                    # 获取现有选项
                    existing_options = await db.execute(
                        select(OptionModel).where(OptionModel.question_id == question.id)
                    )
                    existing_options = existing_options.scalars().all()
                    existing_option_ids = {o.id for o in existing_options}

                    # 处理每个选项
                    for option_data in question_data.options:
                        if hasattr(option_data, 'id') and option_data.id:
                            # 更新现有选项
                            option = next((o for o in existing_options if o.id == option_data.id), None)
                            if option:
                                option.value = option_data.value
                                option.order = option_data.order
                                existing_option_ids.remove(option.id)
                        else:
                            # 创建新选项
                            option = OptionModel(
                                question_id=question.id,
                                value=option_data.value,
                                order=option_data.order
                            )
                            db.add(option)

                    # 删除未使用的选项
                    if existing_option_ids:
                        await db.execute(
                            delete(OptionModel).where(OptionModel.id.in_(existing_option_ids))
                        )

            # 删除未使用的问题
            if existing_question_ids:
                await db.execute(
                    delete(QuestionModel).where(QuestionModel.id.in_(existing_question_ids))
                )

        await db.commit()
        await db.refresh(survey)
        return survey

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新问卷失败: {str(e)}"
        )


# ———————————————— 删除问卷 ————————————————
@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_survey(survey_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SurveyModel).where(SurveyModel.id == survey_id))
    survey = result.scalar_one_or_none()

    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    await db.delete(survey)
    await db.commit()
    return


# ———————————————— 提交问卷回答 ————————————————
@router.post("/{survey_id}/responses")
async def submit_response(
    survey_id: int,
    data: ResponseSubmit,
    db: AsyncSession = Depends(get_db)
):
    # 检查问卷是否存在
    survey_result = await db.execute(select(SurveyModel).where(SurveyModel.id == survey_id))
    survey = survey_result.scalar_one_or_none()

    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 创建提交记录
    response = ResponseModel(survey_id=survey_id)
    db.add(response)
    await db.flush()  # 获取 response.id

    # 保存每道题的答案
    for ans in data.answers:
        # 创建答案记录
        answer = AnswerModel(
            response_id=response.id,
            question_id=ans.question_id,
            answer_text=ans.answer_text,
            answer_rating=ans.answer_rating
        )
        db.add(answer)
        await db.flush()  # 获取 answer.id

        # 如果是选择题，创建选项关联
        if ans.selected_option_ids:
            for order, option_id in enumerate(ans.selected_option_ids):
                choice = AnswerChoiceModel(
                    answer_id=answer.id,
                    option_id=option_id,
                    order=order
                )
                db.add(choice)

    # 更新问卷响应数
    survey.current_responses += 1

    await db.commit()
    return {"message": "提交成功"}


# ———————————————— 生成问卷二维码 ————————————————
@router.get("/{survey_id}/qr")
async def generate_qr(request: Request, survey_id: int):
    # 从请求对象中获取基础 URL
    base_url = str(request.base_url)
    if "8000" in base_url:
        base_url = "http://localhost:5173/"
    # 构建完整的调查链接
    url = f"{base_url}survey/fill/{survey_id}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    img = qr.make_image(fill_color="black", back_color="white")

    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    return StreamingResponse(img_bytes, media_type="image/png")


# ———————————————— 问卷统计 ————————————————

@router.get("/{survey_id}/statistics")
async def get_survey_statistics(
    survey_id: int,
    db: AsyncSession = Depends(get_db)
):
    """获取问卷统计信息"""
    # 检查问卷是否存在
    survey = await db.get(SurveyModel, survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 获取所有问题
    questions = await db.execute(
        select(QuestionModel).where(QuestionModel.survey_id == survey_id)
    )
    questions = questions.scalars().all()

    statistics = {
        "survey_id": survey_id,
        "title": survey.title,
        "total_responses": survey.current_responses,
        "questions": []
    }

    # 统计每个问题的答案
    for question in questions:
        question_stats = {
            "question_id": question.id,
            "text": question.text,
            "type": question.type,
            "statistics": {}
        }

        if question.type in ['single_choice', 'multiple_choice']:
            # 获取选项统计
            options = await db.execute(
                select(OptionModel).where(OptionModel.question_id == question.id)
            )
            options = options.scalars().all()

            for option in options:
                # 统计选择该选项的次数
                count = await db.execute(
                    select(func.count(AnswerChoiceModel.option_id))
                    .where(AnswerChoiceModel.option_id == option.id)
                )
                count = count.scalar()
                question_stats["statistics"][option.value] = count

        elif question.type == 'rating':
            # 获取评分统计
            ratings = await db.execute(
                select(AnswerModel.answer_rating)
                .where(AnswerModel.question_id == question.id)
                .where(AnswerModel.answer_rating.isnot(None))
            )
            ratings = ratings.scalars().all()
            
            if ratings:
                question_stats["statistics"] = {
                    "average": sum(ratings) / len(ratings),
                    "min": min(ratings),
                    "max": max(ratings),
                    "distribution": {
                        str(i): ratings.count(i) for i in range(1, 6)  # 假设评分范围是1-5
                    }
                }

        elif question.type == 'text':
            # 获取文本答案数量
            count = await db.execute(
                select(func.count(AnswerModel.id))
                .where(AnswerModel.question_id == question.id)
                .where(AnswerModel.answer_text.isnot(None))
            )
            question_stats["statistics"]["total_text_answers"] = count.scalar()

        statistics["questions"].append(question_stats)

    return statistics


# ———————————————— 问卷数据导出 ————————————————

@router.get("/{survey_id}/export")
async def export_survey_data(
    survey_id: int,
    db: AsyncSession = Depends(get_db)
):
    """导出问卷数据为CSV"""
    # 检查问卷是否存在
    survey = await db.get(SurveyModel, survey_id)
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 获取所有问题
    questions = await db.execute(
        select(QuestionModel).where(QuestionModel.survey_id == survey_id)
    )
    questions = questions.scalars().all()

    # 获取所有回答
    responses = await db.execute(
        select(ResponseModel).where(ResponseModel.survey_id == survey_id)
    )
    responses = responses.scalars().all()

    # 创建CSV文件
    output = StringIO()
    writer = csv.writer(output)

    # 写入表头
    headers = ["提交时间", "提交者"]
    for question in questions:
        headers.append(question.text)
    writer.writerow(headers)

    # 写入数据
    for response in responses:
        row = [response.submitted_at, response.user_name or ""]
        
        for question in questions:
            # 获取该问题的答案
            answer = await db.execute(
                select(AnswerModel)
                .where(AnswerModel.response_id == response.id)
                .where(AnswerModel.question_id == question.id)
            )
            answer = answer.scalar_one_or_none()

            if answer:
                if question.type in ['single_choice', 'multiple_choice']:
                    # 获取选择的选项
                    choices = await db.execute(
                        select(OptionModel)
                        .join(AnswerChoiceModel)
                        .where(AnswerChoiceModel.answer_id == answer.id)
                        .order_by(AnswerChoiceModel.order)
                    )
                    choices = choices.scalars().all()
                    row.append(", ".join(choice.value for choice in choices))
                elif question.type == 'rating':
                    row.append(str(answer.answer_rating))
                else:  # text
                    row.append(answer.answer_text or "")
            else:
                row.append("")

        writer.writerow(row)

    # 准备下载
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=survey_{survey_id}_data.csv"
        }
    )