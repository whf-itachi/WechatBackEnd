from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_services.database import get_db
from app.logger import get_logger
from app.models import Attachment
from app.models.rag import Question
from app.models.ticket import TicketAttachmentLink, Ticket
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


# 定义请求模型
class FileIdsRequest(BaseModel):
    file_ids: list[str] = []  # 指定 file_ids 类型为字符串列表，默认为空列表

# 根据文档id列表查询相关附件信息
@router.post("/chat/attachments")
async def get_attachments_by_issue(request_data: FileIdsRequest, db: AsyncSession = Depends(get_db)):
    file_ids = request_data.file_ids  # 获取到文件ID列表

    if not file_ids:
        return {"attachments": []}

    # 通过文件id查询相关的附件信息
    stmt = (
        select(Attachment, Ticket.file_id)
        .join(TicketAttachmentLink, Attachment.id == TicketAttachmentLink.attachment_id)
        .join(Ticket, Ticket.id == TicketAttachmentLink.ticket_id)
        .where(Ticket.file_id.in_(file_ids))
        .distinct()
    )

    result = await db.execute(stmt)
    rows = result.all()
    attachments = []
    for attachment, field_id in rows:
        file_info = {
            "field_id": field_id,
            "file_name": attachment.file_name,
            "file_type": attachment.file_type,
            "file_path": attachment.file_path,
        }

        attachments.append(file_info)

    return {"attachments": attachments}


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