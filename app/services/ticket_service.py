import os
from datetime import datetime
from io import BytesIO

import aiofiles
from PIL import Image
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from app.models.ticket import Ticket, TicketAttachmentLink, Attachment
from app.schemas.ticket_schema import TicketUpdate

from typing import List
from app.config import settings
from app.utils.ali.BaiLianRAG import BaiLian


async def create_ticket_service(session: AsyncSession, ticket_data: dict):
    """
    创建新的问题单
    
    Args:
        session: 数据库会话
        ticket_data: 问题单数据字典
        
    Returns:
        Ticket: 创建成功的问题单对象
    """
    try:
        # 确保ticket_data中包含user_id
        if 'user_id' not in ticket_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="创建工单失败: 缺少用户ID"
            )
            
        new_ticket = Ticket(**ticket_data)
        session.add(new_ticket)
        await session.commit()
        await session.refresh(new_ticket)
        return new_ticket
    except Exception as e:
        print(e," ----------------")
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建工单失败: {str(e)}"
        )


async def get_tickets_service(session: AsyncSession):
    """
    获取所有问题单
    
    Args:
        session: 数据库会话
        
    Returns:
        List[Ticket]: 问题单列表
    """
    try:
        # 使用 select 语句查询工单，并预加载 attachments 关系
        query = select(Ticket).options(selectinload(Ticket.attachments))
        result = await session.execute(query)
        return result.scalars().all()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取工单列表失败: {str(e)}"
        )


async def get_ticket_service(session: AsyncSession, ticket_id: int):
    """
    根据ID获取问题单
    
    Args:
        session: 数据库会话
        ticket_id: 问题单ID
        
    Returns:
        Optional[Ticket]: 问题单对象，如果不存在则返回None
    """
    try:
        # 使用 select 语句查询工单，并预加载 attachments 关系
        query = select(Ticket).options(selectinload(Ticket.attachments)).where(Ticket.id == ticket_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取工单详情失败: {str(e)}"
        )


async def update_ticket_service(session: AsyncSession, ticket_id: int, ticket_data: TicketUpdate):
    """
    更新问题单信息
    
    Args:
        session: 数据库会话
        ticket_id: 问题单ID
        ticket_data: 更新的问题单数据
        
    Returns:
        Optional[Ticket]: 更新后的问题单对象，如果不存在则返回None
    """
    try:
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            return None
        for field, value in ticket_data.model_dump(exclude_unset=True).items():
            setattr(ticket, field, value)
        await session.commit()
        await session.refresh(ticket)
        return ticket
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新工单失败: {str(e)}"
        )



def delete_files_with_prefix(directory, prefix_name):
    try:
        base_name, _ = os.path.splitext(prefix_name)
        for filename in os.listdir(directory):
            if filename.startswith(base_name):
                full_path = os.path.join(directory, filename)
                if os.path.isfile(full_path):
                    os.remove(full_path)
                    print(f"已删除：{full_path}")
    except Exception as e:
        print(f"删除文件失败：{e}")


# 根据附件id删除相关的 数据表数据以及 存储文件
async def delete_attachment_by_id(session: AsyncSession, attachment_id: int):
    """
    根据附件ID删除附件及其关联数据

    Args:
        session: 异步数据库会话
        attachment_id: 附件ID

    Returns:
        bool: 成功返回 True，如果附件不存在返回 None
    """
    try:
        # 1. 查询附件是否存在
        result = await session.execute(select(Attachment).where(Attachment.id == attachment_id))
        attachment = result.scalars().first()

        if not attachment:
            return None

        # 2. 删除中间表记录（Ticket 和 Attachment 的关联）
        stmt_link = delete(TicketAttachmentLink).where(TicketAttachmentLink.attachment_id == attachment_id)
        await session.execute(stmt_link)

        # 3. 删除附件数据库记录
        stmt_attachment = delete(Attachment).where(Attachment.id == attachment_id)
        await session.execute(stmt_attachment)

        # 4. 删除物理文件
        delete_files_with_prefix(attachment.file_path, attachment.file_name)

        # 提交事务
        await session.commit()

        return True

    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"删除附件失败: {str(e)}"
        )


# 删除问题单 以及 相关附件信息
async def delete_ticket_service(session: AsyncSession, ticket_id: int):
    """
    删除问题单及其关联的附件、中间表记录和物理文件

    Args:
        session: 数据库会话
        ticket_id: 问题单ID

    Returns:
        bool: 删除成功返回True，如果问题单不存在则返回None
    """
    try:
        # 1. 查询工单是否存在
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            return None

        # 2. 获取该工单关联的所有附件信息并删除
        result = await session.execute(
            select(TicketAttachmentLink.attachment_id).where(TicketAttachmentLink.ticket_id == ticket_id)
        )
        attachment_ids = [row[0] for row in result.all()]
        for attachment_id in attachment_ids:
            await delete_attachment_by_id(session, attachment_id)

        # 3. 删除中间表记录
        stmt = delete(TicketAttachmentLink).where(TicketAttachmentLink.ticket_id == ticket_id)
        await session.execute(stmt)

        # 6. 删除工单
        await session.delete(ticket)
        await session.commit()

        # 7. 删除大模型工单文档
        if ticket.file_id:
            bai_lian = BaiLian()
            bai_lian.delete_rag_document(ticket.file_id)  # 删除文档
            bai_lian.delete_rag_index(ticket.file_id)  # 删除知识库索引文档

        return True

    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除工单失败: {str(e)}"
        )


ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"]
ALLOWED_FILE_TYPES = {
    'image/jpeg', 'image/png', 'application/pdf', 'video/mp4', 'video/quicktime',
    'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
}
MAX_FILE_SIZE = 600 * 1024 * 1024  # 600MB

def resize_image(image: Image.Image, size: tuple):
    """保持比例缩放，裁剪或填充"""
    image.thumbnail(size)
    background = Image.new('RGB', size, (255, 255, 255))
    offset = ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
    background.paste(image, offset)
    return background.convert("RGB")

def get_year_month_sub_path(base_path: str) -> str:
    now = datetime.now()
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")

    return os.path.join(base_path, year_str, month_str)

# 附件上传处理逻辑
async def handle_attachment_files(db: AsyncSession, ticket_id: int, attachments: list):
    upload_dir = get_year_month_sub_path(settings.ATTACHMENT_PATH)
    print("现在要存入的目标目录为: ", upload_dir)
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)

    # 验证附件格式
    for attachment in attachments:
        if attachment.content_type not in ALLOWED_FILE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件类型: {attachment.content_type}"
            )
        if attachment.size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件大小超过限制: {attachment.filename}"
            )

    for attachment in attachments:
        filename = secure_filename(attachment.filename)  # 安全的获取文件名
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_filename = f"{timestamp}_{filename}"
        base_filename, _ = os.path.splitext(new_filename)
        # 保存文件
        file_path = os.path.join(upload_dir, new_filename)

        # 使用异步方式读取文件内容
        contents = await attachment.read()
        # 使用异步方式写入文件
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(contents)

        # 如果是图片，则生成缩略图
        if attachment.content_type in ALLOWED_IMAGE_TYPES:
            image = Image.open(BytesIO(contents))

            # 预览图（适合 PC 端展示）
            preview_img = resize_image(image, (800, 800))
            preview_path = os.path.join(upload_dir, f"{base_filename}_preview.jpg")
            preview_img.save(preview_path, quality=85, optimize=True)

            # 大号缩略图（适合移动端高清展示）
            large_thumb = resize_image(image, (300, 300))
            large_thumbnail_path = os.path.join(upload_dir, f"{base_filename}_large.jpg")
            large_thumb.save(large_thumbnail_path, quality=75, optimize=True)

            # 小号缩略图（适合列表展示）
            small_thumb = resize_image(image, (100, 100))
            small_thumbnail_path = os.path.join(upload_dir, f"{base_filename}_small.jpg")
            small_thumb.save(small_thumbnail_path, quality=65, optimize=True)

        # 创建附件记录
        attachment_record = Attachment(
            file_path=upload_dir,
            file_name=new_filename,
            file_type=attachment.content_type
        )
        db.add(attachment_record)
        await db.flush()  # 获取 attachment_record.id

        # 创建关联关系
        link = TicketAttachmentLink(
            ticket_id=ticket_id,
            attachment_id=attachment_record.id
        )
        db.add(link)