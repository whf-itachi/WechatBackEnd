from fastapi import APIRouter

from app.logger import get_logger
from app.utils.ali.BaiLianRAG import BaiLian
from fastapi import Request
from fastapi.responses import StreamingResponse

from app.utils.rate_limit import rate_limit

router = APIRouter()
logger = get_logger('chat_router')


@router.post("/chat/stream")
async def chat_stream(request: Request):
    ip = request.client.host
    await rate_limit(ip)  # 调用限流逻辑

    body = await request.json()
    issue_str = body.get("message", "")

    llm = BaiLian()

    def event_stream():
        for chunk in llm.stream_chat(issue_str):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/plain")
