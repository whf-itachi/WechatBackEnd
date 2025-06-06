# bai_lian_service.py
import io

from h11 import ERROR
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Question, Ticket
from app.models.rag import Documents
from app.utils.ali.BaiLianRAG import BaiLian


class BaiLianTaskRunner:
    """
    百炼大模型 工作流调用类
    """
    def __init__(self, bai_lian: BaiLian, session: AsyncSession):
        self.bai_lian = bai_lian
        self.session = session

    async def run(self, table_id: int, f_type="ticket"):
        try:
            await self.bai_lian.describe_file()
            self.bai_lian.submit_index_add_documents_job()

            await self._update_table_status(table_id, f_type)
        except Exception as e:
            print("处理失败", e)

    # 更新工单解析状态
    async def _update_table_status(self, table_id: int, f_type: str):
        if f_type == "ticket":
            result = await self.session.execute(select(Ticket).where(Ticket.id == table_id))
            doc = result.scalars().first()
        elif f_type == "question":
            # 更新问题解析状态
            result = await self.session.execute(select(Question).where(Question.id == table_id))
            doc = result.scalars().first()
        elif f_type == "document":
            # 更新文档解析状态
            result = await self.session.execute(select(Documents).where(Documents.id == table_id))
            doc = result.scalars().first()
        else:
            raise ERROR

        if doc:  # 更新file_id和解析状态
            doc.status = 1
            doc.file_id = self.bai_lian.FileId
            await self.session.commit()



# 上传并解析文件的总调用函数
async def process_full_rag_upload(file_bytes: bytes, db: AsyncSession, dict_data: dict):
    bai_lian = BaiLian()
    file_name = dict_data.get("file_name")
    f_type = dict_data.get("f_type")
    table_id = dict_data.get("id")
    bai_lian.tag = dict_data.get("tag")

    file_obj = io.BytesIO(file_bytes)  # 后台再创建内存文件

    # 上传文档
    bai_lian.upload_rag_document(file_name, r_data=file_obj, f_type=f_type)

    # 添加到知识库并修改解析状态
    runner = BaiLianTaskRunner(bai_lian, db)
    await runner.run(table_id=table_id, f_type=f_type)


# 删除大模型文档
async def async_delete_rag_document(db: AsyncSession, file_id: str, f_type="ticket"):
    if f_type == "ticket":
        result = await db.execute(select(Ticket).where(Ticket.file_id == file_id))
    elif f_type == "question":
        result = await db.execute(select(Question).where(Question.file_id == file_id))
    elif f_type == "document":
        result = await db.execute(select(Documents).where(Documents.file_id == file_id))
    else:
        return False

    db_res = result.scalar_one_or_none()
    if not db_res:
        print(f"删除无效文件ID: {file_id}")
        return False

    await db.delete(db_res)
    await db.commit()

    bai_lian = BaiLian()
    bai_lian.delete_rag_document(file_id)  # 删除文档
    bai_lian.delete_rag_index(file_id)  # 删除知识库索引文档
