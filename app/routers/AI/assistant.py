import base64
import mimetypes
import os

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse

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

from app.utils.rate_limit import rate_limit

router = APIRouter()
logger = get_logger('chat_router')


# 流式会话请求
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
    size: str = "small"  # 指定 缩咯图尺寸，默认为小尺寸

# 根据文档id列表查询相关附件信息
@router.post("/chat/attachments")
async def get_attachments_by_issue(request_data: FileIdsRequest, db: AsyncSession = Depends(get_db)):
    print(request_data, ")))))))))))))))))))))))")
    file_ids = request_data.file_ids  # 获取到文件ID列表
    size = request_data.size

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
            "file_id": attachment.id,
            "file_name": attachment.file_name,
            "file_type": attachment.file_type,
            "file_path": attachment.file_path,
            "attachment_id": attachment.id
        }
        if attachment.file_type == "image/png":
            # 添加缩咯图信息
            f_name, _ = os.path.splitext(attachment.file_name)  # 分割扩展名
            attachment_name = f_name + "_" + size + ".jpg"
            f_path = os.path.join(attachment.file_path, attachment_name)
            # 读取文件内容
            with open(f_path, "rb") as file:
                file_content = file.read()

            # 将文件内容转换为 Base64 编码的字符串
            file_content_base64 = base64.b64encode(file_content).decode("utf-8")
            # 将文件内容添加到 file_info 字典中
            file_info["attachment_content"] = file_content_base64
            file_info["attachment_name"] = attachment_name

        attachments.append(file_info)

    # return JSONResponse(content={"attachments": attachments}, media_type="application/json")
    return JSONResponse(content={"code": 200, "data": {"attachments": attachments}, "message": "操作成功"})
    # return {"attachments": attachments}


# 通过附件id查询附件预览 （暂时废弃了，使用静态文件直接访问）
@router.get("/attachment/preview/{attachment_id}")
async def preview_attachment(attachment_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
    attachment = result.scalars().first()

    if not attachment:
        raise HTTPException(status_code=404, detail="附件不存在")

    file_path = os.path.join(attachment.file_path, attachment.file_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        filename=attachment.file_name,
        media_type=attachment.file_type or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename={attachment.file_name}"}
    )


# 反馈信息接口
@router.post("/chat/feedback")
async def create_question(data: QuestionCreate, db: AsyncSession = Depends(get_db)):
    question = Question(
        question=data.question
    )
    db.add(question)
    await db.commit()
    await db.refresh(question)

    # 构建统一格式响应
    response_data = {
        "code": 200,
        "data": '',
        "message": "操作成功"
    }
    return JSONResponse(content=response_data)