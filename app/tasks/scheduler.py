from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import select

from app.db_services.database import async_session_factory
from app.models import Question
from app.utils.ali.BaiLianRAG import BaiLian

scheduler = AsyncIOScheduler()

from aiolimiter import AsyncLimiter
import asyncio
from datetime import datetime, timezone

upload_limiter = AsyncLimiter(max_rate=5, time_period=1)


async def upload_rag_async(q):
    llm = BaiLian()
    file_name = f"question_{q.id}.txt"
    row_data = q.model_dump()

    async with upload_limiter:
        # 运行上传，假设是同步函数，用 to_thread 调用
        res = await asyncio.to_thread(llm.upload_rag_document, f_name=file_name, r_data=row_data)

    return res  # 返回结果，True or False


async def process_pending_questions():
    async with async_session_factory() as db:
        try:
            result = await db.execute(
                select(Question).where(
                    Question.status == 0,
                    Question.is_delete == 0,
                    Question.answers.isnot(None),
                    Question.answers != ""
                )
            )

            pending_questions = result.scalars().all()

            if not pending_questions:
                return

            update_list = []
            for q in pending_questions:
                res = await upload_rag_async(q)
                if res == "success":
                    q.status = 1
                    q.updated_at = datetime.now(timezone.utc)
                    update_list.append(q)
                else:
                    print(f"[{datetime.now()}] 上传失败，问题ID: {q.id}")

            if update_list:
                await db.commit()
                print(f"[{datetime.now()}] 已处理 {len(update_list)} 个问题")

        except Exception as e:
            await db.rollback()
            print(f"[定时任务] 错误：{e}")


def start_scheduler():
    scheduler.add_job(process_pending_questions, IntervalTrigger(minutes=1))
    scheduler.start()
