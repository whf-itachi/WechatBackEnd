from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.db_services.database import get_db
from app.logger import get_logger
from app.models.rag import Question
from app.schemas.rag_schema import QuestionCreate, QuestionRead, QuestionUpdate

router = APIRouter()
logger = get_logger('rag_router')


# 创建问题
@router.post("/questions", response_model=QuestionRead)
async def create_question(data: QuestionCreate, db: AsyncSession = Depends(get_db)):
    question = Question(
        question=data.question
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return question

# 获取问题列表（支持分页）
@router.get("/questions", response_model=list[QuestionRead])
async def list_questions(skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Question).where(Question.is_delete == 0).offset(skip).limit(limit)
    )
    return result.scalars().all()

# 获取单个问题
@router.get("/questions/{question_id}", response_model=QuestionRead)
async def get_question(question_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Question).where(Question.id == question_id, Question.is_delete == 0))
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="问题不存在")
    return question

# 更新问题
@router.put("/questions/{question_id}", response_model=QuestionRead)
async def update_question(
    question_id: int,
    data: QuestionUpdate,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Question).where(Question.id == question_id, Question.is_delete == 0))
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="问题不存在")

    question.answers = data.answers
    question.status = 0  # 修改过后 处理状态恢复为 0，等待定时任务上传后标记为已处理

    # todo：调用大模型删除对应文档

    question.updated_at = datetime.now(timezone.utc)
    db.add(question)
    await db.commit()
    await db.refresh(question)

    return question

# 软删除问题
@router.delete("/questions/{question_id}")
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Question).where(Question.id == question_id, Question.is_delete == 0))
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="问题不存在")

    question.is_delete = 1
    question.updated_at = datetime.now(timezone.utc)
    db.add(question)
    await db.commit()
    return {"message": f"问题 {question_id} 删除成功"}
