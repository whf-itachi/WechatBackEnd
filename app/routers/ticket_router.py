from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from app.db_services.database import get_db
from app.services.ticket_service import delete_ticket_service
from app.schemas.ticket_schema import TicketResponse
from app.dependencies.auth import get_current_user
from app.models.user import User
from typing import List, Optional
from app.logger import get_logger
import os
from datetime import datetime
from app.models.ticket import Ticket, Attachment, TicketAttachmentLink
from sqlalchemy import select

router = APIRouter()
logger = get_logger('ticket_router')

# 文件上传配置
ALLOWED_FILE_TYPES = {
    'image/jpeg', 'image/png', 'application/pdf',
    'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


# 创建问题单
@router.post("/submit")
async def create_ticket(
    device_model: str = Form(...),
    customer: str = Form(...),
    fault_phenomenon: str = Form(...),
    fault_reason: Optional[str] = Form(None),
    handling_method: Optional[str] = Form(None),
    handler: Optional[str] = Form(None),
    attachments: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建工单"""
    logger.info(f"开始创建工单: {device_model}")
    try:
        # 验证文件
        if attachments:
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

        # 创建工单
        ticket = Ticket(
            device_model=device_model,
            customer=customer,
            fault_phenomenon=fault_phenomenon,
            fault_reason=fault_reason,
            handling_method=handling_method,
            handler=handler or current_user.username,
            user_id=current_user.id
        )
        db.add(ticket)
        await db.flush()  # 获取 ticket.id

        # 处理文件上传
        if attachments:
            # 确保上传目录存在
            upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "files")
            if not os.path.exists(upload_dir):
                os.makedirs(upload_dir)

            for attachment in attachments:
                # 生成文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_filename = f"{timestamp}_{attachment.filename}"
                
                # 保存文件
                file_path = os.path.join(upload_dir, new_filename)
                try:
                    # 使用异步方式读取文件内容
                    contents = await attachment.read()
                    # 使用异步方式写入文件
                    with open(file_path, "wb") as buffer:
                        buffer.write(contents)
                except Exception as e:
                    logger.error(f"文件保存失败: {str(e)}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="文件保存失败"
                    )
                
                # 创建附件记录
                attachment_record = Attachment(
                    file_path=file_path,
                    file_type=attachment.content_type
                )
                db.add(attachment_record)
                await db.flush()  # 获取 attachment_record.id

                # 创建关联关系
                link = TicketAttachmentLink(
                    ticket_id=ticket.id,
                    attachment_id=attachment_record.id
                )
                db.add(link)
        
        # 提交事务
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="数据库提交失败"
            )
        
        logger.info(f"工单创建成功: {ticket.id}")
        return {"message": "工单创建成功", "ticket_id": ticket.id}
        
    except HTTPException as e:
        logger.error(f"工单创建失败 - HTTP异常: {str(e)}")
        await db.rollback()
        raise e
    except SQLAlchemyError as e:
        logger.error(f"工单创建失败 - 数据库异常: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="数据库操作失败"
        )
    except Exception as e:
        logger.error(f"工单创建失败 - 系统异常: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "工单创建失败",
                "errors": [str(e)]
            }
        )


# 查询所有问题单
@router.get("/list", response_model=List[TicketResponse])
async def get_tickets(
    page: int = 1,
    pageSize: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询所有问题单"""
    logger.info(f"收到获取问题单列表请求，当前用户: {current_user.id}")
    try:
        # 查询工单
        stmt = select(Ticket).offset((page - 1) * pageSize).limit(pageSize)
        result = await db.execute(stmt)
        tickets = result.scalars().all()

        # 获取所有工单ID
        ticket_ids = [ticket.id for ticket in tickets]
        
        # 一次性查询所有工单的附件
        attachments_map = {}
        if ticket_ids:
            stmt = select(
                TicketAttachmentLink.ticket_id,
                Attachment
            ).join(
                Attachment,
                TicketAttachmentLink.attachment_id == Attachment.id
            ).where(
                TicketAttachmentLink.ticket_id.in_(ticket_ids)
            )
            
            result = await db.execute(stmt)
            for row in result:
                ticket_id = row[0]
                attachment = row[1]
                if ticket_id not in attachments_map:
                    attachments_map[ticket_id] = []
                
                # 从文件路径中提取文件名
                file_name = os.path.basename(attachment.file_path)
                attachments_map[ticket_id].append({
                    "id": attachment.id,
                    "file_path": attachment.file_path,
                    "file_type": attachment.file_type,
                    "upload_time": attachment.upload_time,
                    "file_name": file_name
                })

        # 构建响应
        response_data = []
        for ticket in tickets:
            ticket_dict = {
                "id": ticket.id,
                "device_model": ticket.device_model,
                "customer": ticket.customer,
                "fault_phenomenon": ticket.fault_phenomenon,
                "fault_reason": ticket.fault_reason,
                "handling_method": ticket.handling_method,
                "handler": ticket.handler,
                "user_id": ticket.user_id,
                "create_at": ticket.create_at,
                "attachments": attachments_map.get(ticket.id, [])
            }
            response_data.append(ticket_dict)

        logger.info(f"成功获取问题单列表，共 {len(tickets)} 条记录")
        return response_data
    except HTTPException as e:
        logger.error(f"获取问题单列表失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取问题单列表失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询所有问题单时发生错误: {str(e)}"
        )


# 根据问题单 id 查询问题单信息
@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据ID获取问题单信息"""
    logger.info(f"收到获取问题单信息请求，问题单ID: {ticket_id}，当前用户: {current_user.id}")
    try:
        # 查询工单
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()
        
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该问题单"
            )

        # 查询附件
        stmt = select(Attachment).join(
            TicketAttachmentLink,
            Attachment.id == TicketAttachmentLink.attachment_id
        ).where(TicketAttachmentLink.ticket_id == ticket_id)
        
        result = await db.execute(stmt)
        attachments = result.scalars().all()
        
        # 处理附件信息
        ticket_attachments = []
        for attachment in attachments:
            # 从文件路径中提取文件名
            file_name = os.path.basename(attachment.file_path)
            ticket_attachments.append({
                "id": attachment.id,
                "file_path": attachment.file_path,
                "file_type": attachment.file_type,
                "upload_time": attachment.upload_time,
                "file_name": file_name
            })
        
        # 构建响应
        response_data = {
            "id": ticket.id,
            "device_model": ticket.device_model,
            "customer": ticket.customer,
            "fault_phenomenon": ticket.fault_phenomenon,
            "fault_reason": ticket.fault_reason,
            "handling_method": ticket.handling_method,
            "handler": ticket.handler,
            "user_id": ticket.user_id,
            "create_at": ticket.create_at,
            "attachments": ticket_attachments
        }

        logger.info(f"成功获取问题单信息: {ticket.id}")
        return response_data
    except HTTPException as e:
        logger.error(f"获取问题单信息失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取问题单信息失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询问题单信息时发生错误: {str(e)}"
        )


# 根据问题单 id 修改问题单信息
@router.put("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    ticket_id: int,
    device_model: str = Form(...),
    customer: str = Form(...),
    fault_phenomenon: str = Form(...),
    fault_reason: Optional[str] = Form(None),
    handling_method: Optional[str] = Form(None),
    handler: Optional[str] = Form(None),
    attachments: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新问题单信息"""
    logger.info(f"收到更新问题单信息请求，问题单ID: {ticket_id}，当前用户: {current_user.id}")
    try:
        # 获取当前工单信息
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()
        
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该问题单"
            )

        # 更新工单基本信息
        ticket.device_model = device_model
        ticket.customer = customer
        ticket.fault_phenomenon = fault_phenomenon
        ticket.fault_reason = fault_reason
        ticket.handling_method = handling_method
        ticket.handler = handler or current_user.username
        ticket.user_id = current_user.id

        # 处理附件更新
        if attachments is not None:  # 只有当附件字段存在时才处理
            # 验证新上传的文件
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

            # 删除原有附件
            # 1. 查询原有附件关联
            stmt = select(TicketAttachmentLink).where(TicketAttachmentLink.ticket_id == ticket_id)
            result = await db.execute(stmt)
            old_links = result.scalars().all()
            
            if old_links:
                # 2. 获取原有附件ID
                old_attachment_ids = [link.attachment_id for link in old_links]
                
                # 3. 查询原有附件
                stmt = select(Attachment).where(Attachment.id.in_(old_attachment_ids))
                result = await db.execute(stmt)
                old_attachments = result.scalars().all()
                
                # 4. 删除原有附件文件
                for attachment in old_attachments:
                    try:
                        if os.path.exists(attachment.file_path):
                            os.remove(attachment.file_path)
                    except Exception as e:
                        logger.error(f"删除附件文件失败: {str(e)}")
                
                # 5. 删除原有附件记录和关联
                for link in old_links:
                    await db.delete(link)
                for attachment in old_attachments:
                    await db.delete(attachment)

            # 保存新上传的附件
            if attachments:  # 只有当有附件时才保存
                # 确保上传目录存在
                upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "files")
                if not os.path.exists(upload_dir):
                    os.makedirs(upload_dir)

                for attachment in attachments:
                    # 生成文件名
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    new_filename = f"{timestamp}_{attachment.filename}"
                    
                    # 保存文件
                    file_path = os.path.join(upload_dir, new_filename)
                    try:
                        contents = await attachment.read()
                        with open(file_path, "wb") as buffer:
                            buffer.write(contents)
                    except Exception as e:
                        logger.error(f"文件保存失败: {str(e)}")
                        raise HTTPException(
                            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="文件保存失败"
                        )
                    
                    # 创建附件记录
                    attachment_record = Attachment(
                        file_path=file_path,
                        file_type=attachment.content_type
                    )
                    db.add(attachment_record)
                    await db.flush()  # 获取 attachment_record.id

                    # 创建关联关系
                    link = TicketAttachmentLink(
                        ticket_id=ticket.id,
                        attachment_id=attachment_record.id
                    )
                    db.add(link)

        # 提交事务
        try:
            await db.commit()
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="数据库提交失败"
            )

        # 构建响应
        # 查询更新后的附件信息
        stmt = select(Attachment).join(
            TicketAttachmentLink,
            Attachment.id == TicketAttachmentLink.attachment_id
        ).where(TicketAttachmentLink.ticket_id == ticket_id)
        
        result = await db.execute(stmt)
        attachments = result.scalars().all()
        
        # 处理附件信息
        ticket_attachments = []
        for attachment in attachments:
            file_name = os.path.basename(attachment.file_path)
            ticket_attachments.append({
                "id": attachment.id,
                "file_path": attachment.file_path,
                "file_type": attachment.file_type,
                "upload_time": attachment.upload_time,
                "file_name": file_name
            })

        response_data = {
            "id": ticket.id,
            "device_model": ticket.device_model,
            "customer": ticket.customer,
            "fault_phenomenon": ticket.fault_phenomenon,
            "fault_reason": ticket.fault_reason,
            "handling_method": ticket.handling_method,
            "handler": ticket.handler,
            "user_id": ticket.user_id,
            "create_at": ticket.create_at,
            "attachments": ticket_attachments
        }

        logger.info(f"成功更新问题单信息: {ticket.id}")
        return response_data
    except HTTPException as e:
        logger.error(f"更新问题单信息失败 - HTTP异常: {str(e)}")
        await db.rollback()
        raise e
    except Exception as e:
        logger.error(f"更新问题单信息失败 - 系统异常: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新问题单信息时发生错误: {str(e)}"
        )


# 根据问题单 id 删除问题单
@router.delete("/{ticket_id}")
async def delete_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """删除问题单"""
    logger.info(f"收到删除问题单请求，问题单ID: {ticket_id}，当前用户: {current_user.id}")
    try:
        result = await delete_ticket_service(db, ticket_id)
        logger.info(f"成功删除问题单，问题单ID: {ticket_id}")
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该问题单"
            )
        return {"message": "问题单删除成功"}
    except HTTPException as e:
        logger.error(f"删除问题单失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"删除问题单失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除问题单时发生错误: {str(e)}"
        )
