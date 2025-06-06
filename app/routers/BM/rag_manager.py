from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks, Form
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.db_services.database import get_db
from app.logger import get_logger
from app.models.rag import Question, Documents
from app.schemas.rag_schema import QuestionCreate, QuestionRead, QuestionUpdate
from app.services.baiLian_service import process_full_rag_upload, async_delete_rag_document

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
    background_tasks: BackgroundTasks,
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

    # 调用大模型接口删除对应文档
    if question.file_id:
        await async_delete_rag_document(db, file_id=question.file_id, f_type="question")
    # 根据修改后的内容重新提交大模型
    row_data = question.model_dump()
    content = '\n'.join(f'{key}: {value}' for key, value in row_data.items())
    file_bytes = content.encode('utf-8')

    dict_data = {
        "id": question.id,
        "f_type": "question",
        "file_name": f"question_{question.id}.txt"
    }

    background_tasks.add_task(process_full_rag_upload, file_bytes, db, dict_data)

    question.updated_at = datetime.now(timezone.utc)
    db.add(question)
    await db.commit()
    await db.refresh(question)

    return question

# 删除问题
@router.delete("/questions/{question_id}")
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Question).where(Question.id == question_id, Question.is_delete == 0))
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="问题不存在")
    print(question.file_id)
    if question.file_id:
        await async_delete_rag_document(db, file_id=question.file_id, f_type="question")
    else:
        question.is_delete = 1
        question.updated_at = datetime.now(timezone.utc)
        db.add(question)
        await db.commit()
    return {"message": f"问题 {question_id} 删除成功"}


# 添加知识库文档接口
@router.post("/documents")
async def add_rag_documents(background_tasks: BackgroundTasks,
                            file: UploadFile = File(...),
                            tag: str = Form(""),
                            db:AsyncSession = Depends(get_db)):
    max_file_size = 1024 * 1024 * 100  # 100 MB
    if file.size > max_file_size:
        raise HTTPException(status_code=400, detail="文件超过100M请拆分后重新上传")

    # 判断是否已经存在同名文档
    result = await db.execute(select(Documents).where(Documents.file_name == file.filename))
    existing_doc = result.scalars().first()
    if existing_doc:
        raise HTTPException(status_code=400, detail="文件名已存在")

    # 上传成功后进行文档表数据创建
    new_document = Documents(file_name=file.filename, tag=tag, created_at=datetime.now())
    db.add(new_document)
    await db.commit()
    await db.refresh(new_document)

    file_bytes = await file.read()
    # 上传文档，并解析到数据库，修改解析状态
    dict_data = {
        "id": new_document.id,
        "f_type": "document",
        "tag": tag,
        "file_name": file.filename
    }
    background_tasks.add_task(process_full_rag_upload, file_bytes, db, dict_data)

    return {"info": f"文件 {file.filename} 已成功上传", "document_id": new_document.id}


# 获取上传文档列表（支持分页）
@router.get("/documents")
async def list_questions(skip: int = 0, limit: int = 10, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Documents).where(Documents.is_delete == 0).offset(skip).limit(limit)
    )
    return result.scalars().all()