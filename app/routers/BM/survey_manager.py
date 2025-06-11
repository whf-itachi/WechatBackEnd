from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

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
    ResponseSubmit,
    AnswerSubmit
)

router = APIRouter()


# ———————————————— 获取所有问卷（带分页、过滤） ————————————————
@router.get("/", response_model=List[SurveyOut])
async def list_surveys(
    skip: int = 0,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(SurveyModel)
        .offset(skip)
        .limit(limit)
    )
    surveys = result.scalars().all()

    survey_list = []
    for survey in surveys:
        # 获取问卷的响应数量
        count_result = await db.execute(
            select(ResponseModel).where(ResponseModel.survey_id == survey.id)
        )
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
async def create_survey(
    survey_data: SurveyCreate,
    db: AsyncSession = Depends(get_db)
):
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

    # 查询每个问题的选项
    for q in questions:
        option_result = await db.execute(
            select(OptionModel).where(OptionModel.question_id == q.id)
        )
        q.options = option_result.scalars().all()

    survey.questions = questions
    return survey


# ———————————————— 更新问卷信息 ————————————————
@router.put("/{survey_id}", response_model=SurveyOut)
async def update_survey(
    survey_id: int,
    survey_data: SurveyUpdate,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(SurveyModel).where(SurveyModel.id == survey_id))
    survey = result.scalar_one_or_none()

    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 更新字段
    for key, value in survey_data.dict(exclude_unset=True).items():
        setattr(survey, key, value)

    await db.commit()
    await db.refresh(survey)
    return survey


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
import qrcode
from io import BytesIO
from fastapi.responses import StreamingResponse

@router.get("/{survey_id}/qr")
async def generate_qr(survey_id: int):
    base_url = "https://yourdomain.com/survey/fill"
    url = f"{base_url}?survey_id={survey_id}"

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    img = qr.make_image(fill_color="black", back_color="white")

    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    return StreamingResponse(img_bytes, media_type="image/png")