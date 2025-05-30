from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_services.database import get_db
from app.logger import get_logger
from app.models.rag import Question
from app.schemas.rag_schema import QuestionCreate
from app.utils.ali.BaiLianRAG import BaiLian
from fastapi import Request
from fastapi.responses import StreamingResponse

from app.utils.rate_limit import rate_limit

router = APIRouter()
logger = get_logger('chat_router')


@router.post("/chat/stream")
async def chat_stream(request: Request):
    ip = request.client.host
    await rate_limit(ip)

    body = await request.json()
    issue_str = body.get("message", "")

    llm = BaiLian()

    def event_stream():
        for chunk in llm.stream_chat(issue_str):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/plain")


# 反馈信息接口
@router.post("/feedback")
async def create_question(data: QuestionCreate, db: AsyncSession = Depends(get_db)):
    question = Question(
        question=data.question
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return question