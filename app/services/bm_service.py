from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_services.redis_client import get_evaluator_records, delete_all_records, clear_evaluator_records
from app.models.survey import SurveyAnswer, SurveyResponse, SurveyEvaluationAssignment
import json


# 根据redis中数据创建绩效评价记录，并回填已提交的评分
async def create_evaluations_from_redis(
    db: AsyncSession,
    temporary_token: str,
    get_all_records_func: callable
):
    """
    流程：
    1. 从 get_all_records_func 获取“待创建的评价任务”（邀请信息）
    2. 创建 SurveyEvaluationAssignment（pending）
    3. 从 get_evaluator_records 获取“已提交的评分”
    4. 回填评分，更新 assignment 状态为 completed
    """
    # 1. 获取待创建的任务（来自 add_question_ename）
    pending_invitations = await get_all_records_func(temporary_token)  # list of dict
    if not pending_invitations:
        return
    print("获取到redis中的 pending_invitations 为: ", pending_invitations)
    # 2. 获取已提交的评分（来自 add_evaluate_info）

    created_assignments = []
    for record in pending_invitations:
        if not all(k in record for k in ['question_id', 'evaluator_name']):
            continue

        question_id = record['question_id']
        evaluator_name = record['evaluator_name']

        # 🔍 查找对应的 answer_id
        result = await db.execute(
            select(SurveyAnswer.id)
            .join(SurveyResponse, SurveyAnswer.response_id == SurveyResponse.id)
            .where(SurveyResponse.temporary_token == temporary_token)
            .where(SurveyAnswer.question_id == question_id)
        )
        answer_id = result.scalar_one_or_none()
        print("pending_invitations后面获取answer_id: ", answer_id)
        if not answer_id:
            continue  # 答案未生成，跳过

        # 防重：检查是否已存在该 assignment
        exists = await db.execute(
            select(SurveyEvaluationAssignment.id)
            .where(
                SurveyEvaluationAssignment.answer_id == answer_id,
                SurveyEvaluationAssignment.evaluator_name == evaluator_name
            )
        )
        if exists.scalar_one_or_none():
            continue

        assignment = SurveyEvaluationAssignment(
            answer_id=answer_id,
            evaluator_name=evaluator_name,
            status="pending"
            # created_at 自动填充
        )
        db.add(assignment)
        created_assignments.append({
            "assignment": assignment,
            "answer_id": answer_id,
            "question_id": question_id,
            "evaluator_name": evaluator_name
        })

    await db.commit()  # 提交所有 assignment

    submitted_evaluations = await get_evaluator_records(temporary_token)  # list of dict
    print("submitted_evaluations is:", submitted_evaluations)
    submitted_map = {
        (item["question_id"], item["evaluator_name"]): item["evaluation_score"]
        for item in submitted_evaluations
        if all(k in item for k in ["question_id", "", "evaluator_name", "evaluation_score"])
    }
    id_map = {
        (item["question_id"], item["evaluator_name"]): item["evaluator_id"]
        for item in submitted_evaluations
        if all(k in item for k in ["question_id", "evaluator_name", "evaluator_id"])
    }
    print(submitted_map)
    print(id_map)
    # 如果有些 assignment 创建时没有 score，但现在有提交，就更新
    for item in created_assignments:
        if item["assignment"].status == "pending":
            # 检查是否有后来提交的评分
            score = submitted_map.get((item["question_id"], item["evaluator_name"]))
            evaluator_id = id_map.get((item["question_id"], item["evaluator_name"]))

            print("得到分数为：", score)
            if score is not None:
                # 更新 assignment
                await db.execute(
                    update(SurveyEvaluationAssignment)
                    .where(SurveyEvaluationAssignment.answer_id == item["answer_id"])
                    .where(SurveyEvaluationAssignment.evaluator_name == item["evaluator_name"])
                    .values(evaluation_score=score, evaluator_id=evaluator_id, status="completed")
                )
    await db.commit()

    await delete_all_records(temporary_token)
    await clear_evaluator_records(temporary_token)