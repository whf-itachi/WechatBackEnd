import traceback
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db_services.database import get_db
from app.db_services.redis_client import *
from app.logger import get_logger
from app.models import User
from app.models.survey import *
from app.schemas.survey_schema import *

router = APIRouter()
logger = get_logger('Survey_post_router')


@router.post("/evaluation/responses")
async def create_batch_evaluation_assignments(
    data: CreateEvaluationAssignmentBatch,
    db: AsyncSession = Depends(get_db)
):
    """
    批量提交评价任务
    """
    try:
        for item in data.evaluations:
            # 1. 获取对应 answer_id
            answer_result = await db.execute(
                select(SurveyAnswer.id)
                .where(SurveyAnswer.response_id == data.response_id)
                .where(SurveyAnswer.question_id == item.question_id)
            )
            answer_id = answer_result.scalar_one_or_none()
            if not answer_id:
                raise HTTPException(
                    status_code=404,
                    detail=f"未找到问题ID {item.question_id} 对应的答案记录"
                )

            # 2. 检查是否已完成评价
            exists_result = await db.execute(
                select(SurveyEvaluationAssignment.id)
                .where(SurveyEvaluationAssignment.answer_id == answer_id)
                .where(SurveyEvaluationAssignment.evaluator_id == data.evaluator_id)
                .where(SurveyEvaluationAssignment.status == "completed")
            )
            if exists_result.first():
                raise HTTPException(
                    status_code=400,
                    detail=f"问题ID {item.question_id} 已提交，不可重复作答"
                )

            # 3. 获取对应评价任务
            eval_result = await db.execute(
                select(SurveyEvaluationAssignment)
                .where(SurveyEvaluationAssignment.answer_id == answer_id)
                .where(SurveyEvaluationAssignment.evaluator_id == data.evaluator_id)
            )

            evaluation_assignment = eval_result.scalar_one_or_none()
            if not evaluation_assignment:
                raise HTTPException(
                    status_code=404,
                    detail=f"未找到问题ID {item.question_id} 的评价任务"
                )

            # 4. 更新评价任务
            evaluation_assignment.evaluation_score = item.evaluation_score
            evaluation_assignment.evaluator_id = data.evaluator_id
            evaluation_assignment.status = "completed"
            db.add(evaluation_assignment)  # 标记为需要 commit

        # 5. 提交事务
        await db.commit()

        return {
            "code": 200,
            "message": "评价任务批量提交成功"
        }

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail="系统错误"
        )


# 创建问卷
@router.post("/", response_model=SurveyOut)
async def create_survey(survey_data: SurveyCreate, db: AsyncSession = Depends(get_db)):
    try:
        survey = SurveyTable(
            title=survey_data.title,
            description=survey_data.description,
            expire_at=survey_data.expire_at,
            require_login=survey_data.require_login,
            current_responses=0
        )
        db.add(survey)
        await db.flush()
        for question_data in survey_data.questions:
            question = SurveyQuestion(
                survey_id=survey.id,
                text=question_data.text,
                type=question_data.type,
                required=question_data.required
            )
            db.add(question)
            await db.flush()
            if question_data.type in ['single_choice', 'multiple_choice'] and question_data.options:
                for option_data in question_data.options:
                    option = SurveyOption(
                        question_id=question.id,
                        value=option_data.value,
                        is_other=option_data.is_other
                    )
                    db.add(option)
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
        print(traceback.format_exc())
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建问卷失败: {str(e)}"
        )


# 创建新的汇总问卷
@router.post("/survey_summary/", response_model=SummaryDetailOut)
async def create_summary(data: SummaryCreateIn,db: AsyncSession = Depends(get_db)):
    # 插入主表
    new_summary = SurveySummaryTable(
        name=data.name,
        description=data.description
    )
    db.add(new_summary)
    await db.flush()

    # 插入关联表
    for relation in data.relations:
        db_relation = SurveySummaryLinks(
            summary_id=new_summary.id,
            survey_id=relation.survey_id,
            description=relation.description
        )
        db.add(db_relation)

    await db.commit()
    await db.refresh(new_summary)

    # 查询完整数据并预加载 relations
    result = await db.execute(
        select(SurveySummaryTable)
        .options(selectinload(SurveySummaryTable.relations))
        .where(SurveySummaryTable.id == new_summary.id)
    )
    summary = result.scalars().first()

    return SummaryDetailOut(
        id=summary.id,
        name=summary.name,
        description=summary.description,
        created_at=summary.created_at,
        relations=[
            SummaryRelationOut.model_validate(r) for r in summary.relations
        ]
    )


# 提交问卷回答
@router.post("/{survey_id}/responses", response_model=dict)
async def submit_response(survey_id: int,data: ResponseSubmit,db: AsyncSession = Depends(get_db)):
    print(data, "00000000000000000000000")
    # --------------------------
    # 1. 基础校验：问卷存在性 + 有效期
    # --------------------------
    survey_result = await db.execute(select(SurveyTable).where(SurveyTable.id == survey_id))
    survey = survey_result.scalar_one_or_none()
    if not survey:
        raise HTTPException(status_code=404, detail="问卷不存在")

    # 校验问卷是否过期
    current_time = datetime.now()
    if survey.expire_at and survey.expire_at < current_time:
        raise HTTPException(
            status_code=400,
            detail=f"问卷已过期（截止时间：{survey.expire_at.strftime('%Y-%m-%d %H:%M:%S')}），无法提交"
        )

    # --------------------------
    # 2. 预查询：当前问卷的“多人评分类问题”（type=evaluate）
    # --------------------------
    # 目的：快速判断提交的答案是否需要创建评价任务
    evaluate_question_result = await db.execute(
        select(SurveyQuestion.id)
        .where(SurveyQuestion.survey_id == survey_id)
        .where(SurveyQuestion.type == "evaluate")  # 标记为“多人评分”的问题类型
    )
    # 转为集合，便于后续O(1)判断
    evaluate_question_ids = set(evaluate_question_result.scalars().all())

    user_name = await db.scalar(select(User.name).where(User.id == data.evaluator_id))
    print(".get user_name is : ", user_name)

    response = SurveyResponse(survey_id=survey_id)
    db.add(response)
    await db.flush()  # 触发数据库自增ID生成，用于后续关联

    # --------------------------
    # 4. 遍历提交的答案，创建答案记录 + 评价任务（如需）
    # --------------------------
    for ans in data.answers:
        # --------------------------
        # 4.1 创建答案记录（SurveyAnswer）
        # --------------------------
        answer = SurveyAnswer(
            response_id=response.id,  # 关联当前答卷
            question_id=ans.question_id,  # 关联问题
            answer_text=ans.answer_text,  # 文本类答案（如简答题）
            answer_rating=ans.answer_rating  # 评分类答案（如星级评分）
        )
        db.add(answer)
        await db.flush()  # 生成answer.id，用于关联评价任务/选项

        # --------------------------
        # 4.2 处理选项（单选/多选/“其他”，复用原有逻辑）
        # --------------------------
        selected_ids: List[int] = []
        # 合并单选/多选的选项ID
        if ans.selected_option_id is not None:
            selected_ids.append(ans.selected_option_id)
        if ans.selected_option_ids:
            selected_ids.extend(ans.selected_option_ids)

        if selected_ids:
            # 批量查询选项详情（含is_other标记）
            option_result = await db.execute(
                select(SurveyOption).where(SurveyOption.id.in_(selected_ids))
            )
            option_list = option_result.scalars().all()
            # 处理“其他，请说明”的自定义值
            other_text_map: Dict[str, str] = ans.other_text or {}

            for option in option_list:
                # 从other_text中匹配选项ID（支持字符串/整数key，如{"123": "自定义内容"}或{123: "自定义内容"}）
                custom_value = other_text_map.get(str(option.id)) or other_text_map.get(option.id)

                # 创建选项关联记录
                answer_choice = SurveyAnswerChoice(
                    answer_id=answer.id,
                    option_id=option.id,
                    custom_value=custom_value
                )
                db.add(answer_choice)

        # --------------------------
        # 4.3 关键：判断是否需要创建“多人评分任务”（SurveyEvaluationAssignment）
        # --------------------------
        if ans.question_id in evaluate_question_ids:  # 对于多个 需要多人评价的问题
            # 校验：评价者ID必须存在（否则无法创建任务）
            if data.evaluator_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"问题ID[{ans.question_id}]为多人评分类问题，需传入evaluator_id（评价者ID）"
                )
            print("111111111111:", answer.id, user_name, ans.answer_evaluate)
            # 创建评价任务记录
            evaluation_assignment = SurveyEvaluationAssignment(
                answer_id=answer.id,  # 关联当前答案（即“被评价的答案”）
                evaluator_id=data.evaluator_id,  # 评价者id
                evaluation_score=ans.answer_evaluate,  # 评分结果
                identity="master",
                status="completed"  # 评分状态完成
            )
            db.add(evaluation_assignment)

            # --------------------------
            # 4.4 处理邀请的评价任务（invited）
            # --------------------------
            invited_user_ids = data.invited_users.get(ans.question_id, []) if data.invited_users else []
            if invited_user_ids:
                for invited_id in invited_user_ids:
                    invited_assignment = SurveyEvaluationAssignment(
                        answer_id=answer.id,  # 对应当前问题的答案
                        evaluator_id=invited_id,  # 受邀评价人
                        identity="invited",
                        status="pending"
                    )
                    db.add(invited_assignment)

    # --------------------------
    # 5. 更新问卷提交数 + 提交事务
    # --------------------------
    survey.current_responses += 1  # 自增提交次数
    await db.commit()  # 批量写入所有记录（response/answer/choice/evaluation）
    await db.refresh(response)  # 刷新对象，获取最新数据库状态（可选）
    print("2222222222:", evaluate_question_ids)

    # --------------------------
    # 6. 返回结果（含关键ID，便于后续查询）
    # --------------------------
    return {
        "code": 200,
        "message": "问卷提交成功",
        "data": {
            "response_id": response.id,  # 答卷ID（可用于查询详情）
            "survey_id": survey_id,
            "submitted_at": response.submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
            "total_responses": survey.current_responses  # 当前问卷总提交数
        }
    }


# 分享二维码，提交redis邀请人信息
@router.post("/evaluate/share_qr/add_evaluation", response_model=ShareEvaluationOut)
async def share_evaluation(
        data: ShareEvaluationIn
):
    """
    存储分享的二维码信息到Redis
    - 调用add_question_ename函数避免重复存储
    - 返回操作结果及时间戳
    """
    print("---------------: share_evaluation")
    try:
        result = await add_question_ename(
            token=data.temporary_token,
            question_id=data.question_id,
            evaluator_name=data.evaluator_name
        )

        if result:
            return ShareEvaluationOut(
                success=True,
                message="分享信息存储成功",
                data={
                    "token": data.temporary_token,
                    "question_id": data.question_id,
                    "evaluator_name": data.evaluator_name
                },
                created_at=datetime.now()
            )
        else:
            return ShareEvaluationOut(
                success=False,
                message="该分享信息已存在",
                data={
                    "token": data.temporary_token,
                    "question_id": data.question_id,
                    "evaluator_name": data.evaluator_name
                },
                created_at=datetime.now()
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"存储分享信息失败: {str(e)}"
        )
