import io

from fastapi import BackgroundTasks

from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from app.db_services.database import get_db
from app.services.baiLian_service import process_full_rag_upload
from app.services.ticket_service import delete_ticket_service
from app.schemas.ticket_schema import TicketResponse
from app.dependencies.auth import get_current_user
from app.models.user import User
from typing import List, Optional
from app.logger import get_logger
import os
from datetime import datetime
from app.models.ticket import Ticket, Attachment, TicketAttachmentLink, DeviceModel, Customer
from sqlalchemy import select, cast, String, or_
import json

from app.utils.ali.BaiLianRAG import BaiLian

router = APIRouter()
logger = get_logger('ticket_router')

# 文件上传配置
ALLOWED_FILE_TYPES = {
    'image/jpeg', 'image/png', 'application/pdf', 'video/mp4', 'video/quicktime',
    'application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
}
MAX_FILE_SIZE = 600 * 1024 * 1024  # 600MB


# 创建问题单
@router.post("/submit")
async def create_ticket(
    background_tasks: BackgroundTasks,
    device_model: str = Form(...),
    customer: str = Form(...),
    address: Optional[str] = Form(None),
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
            address=address,
            fault_phenomenon=fault_phenomenon,
            fault_reason=fault_reason,
            handling_method=handling_method,
            handler=handler or current_user.username,
            user_id=current_user.id
        )
        db.add(ticket)
        await db.flush()

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

        row_data = ticket.model_dump()
        content = '\n'.join(f'{key}: {value}' for key, value in row_data.items())
        file_bytes = content.encode('utf-8')

        dict_data = {
            "id": ticket.id,
            "f_type": "ticket",
            "file_name": f"ticket_{ticket.id}.txt"
        }

        background_tasks.add_task(process_full_rag_upload, file_bytes, db, dict_data)

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
                "address": ticket.address,
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


# 查询当前用户的所有问题单
@router.get("/my-tickets", response_model=List[TicketResponse])
async def get_my_tickets(
        page: int = Query(1, ge=1, description="页码，从1开始"),
        pageSize: int = Query(10, ge=1, le=100, description="每页数量，最大100"),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """查询当前用户的所有问题单"""
    logger.info(f"收到获取当前用户问题单列表请求，用户ID: {current_user.id}")
    try:
        # 查询当前用户的工单
        stmt = select(Ticket).where(
            Ticket.user_id == current_user.id
        ).offset((page - 1) * pageSize).limit(pageSize)

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
                "address": ticket.address,
                "fault_phenomenon": ticket.fault_phenomenon,
                "fault_reason": ticket.fault_reason,
                "handling_method": ticket.handling_method,
                "handler": ticket.handler,
                "user_id": ticket.user_id,
                "create_at": ticket.create_at,
                "attachments": attachments_map.get(ticket.id, [])
            }
            response_data.append(ticket_dict)

        logger.info(f"成功获取当前用户问题单列表，共 {len(tickets)} 条记录")
        return response_data
    except HTTPException as e:
        logger.error(f"获取当前用户问题单列表失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取当前用户问题单列表失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询当前用户问题单时发生错误: {str(e)}"
        )



# 对所有字段进行全量字符串查询
@router.get("/search", response_model=List[TicketResponse])
async def search_all_fields(
        query: str = Query(..., min_length=1),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """根据关键词搜索工单"""
    logger.info(f"收到搜索工单请求，关键词: {query}，当前用户: {current_user.id}")
    try:
        # 构建搜索条件
        model = Ticket
        columns = [getattr(model, column.name) for column in model.__table__.columns]
        conditions = [cast(col, String).like(f"%{query}%") for col in columns]

        # 执行搜索
        stmt = select(model).where(or_(*conditions))
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
                "address": ticket.address,
                "fault_phenomenon": ticket.fault_phenomenon,
                "fault_reason": ticket.fault_reason,
                "handling_method": ticket.handling_method,
                "handler": ticket.handler,
                "user_id": ticket.user_id,
                "create_at": ticket.create_at,
                "attachments": attachments_map.get(ticket.id, [])
            }
            response_data.append(ticket_dict)

        logger.info(f"成功搜索工单，共 {len(tickets)} 条记录")
        return response_data
    except Exception as e:
        logger.error(f"搜索工单失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"搜索工单时发生错误: {str(e)}"
        )


@router.get("/device_models", summary="获取设备型号列表")
async def list_device_models(db: AsyncSession = Depends(get_db)):
    """查询设备型号"""
    try:
        result = await db.execute(select(DeviceModel))
        items = result.scalars().all()

        return {"data": items}
    except Exception as e:
        logger.error(f"查询设备型号失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询机型报错: {str(e)}"
        )


@router.get("/customers", summary="获取客户列表")
async def list_customers(db: AsyncSession = Depends(get_db)):
    """获取客户列表（全部）"""
    try:
        result = await db.execute(select(Customer))
        items = result.scalars().all()

        return {"data": items}
    except Exception as e:
        logger.error(f"查询客户信息失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询客户报错: {str(e)}"
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
            "address": ticket.address,
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
    address: Optional[str] = Form(None),
    fault_phenomenon: str = Form(...),
    fault_reason: Optional[str] = Form(None),
    handling_method: Optional[str] = Form(None),
    handler: Optional[str] = Form(None),
    delete_list: Optional[str] = Form(None),  # 修改为字符串类型，前端传入JSON字符串
    attachments: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新问题单信息"""
    # 打印入参
    logger.info(f"更新问题单入参: ticket_id={ticket_id}, device_model={device_model}, "
                f"customer={customer}, address={address}, fault_phenomenon={fault_phenomenon}, "
                f"fault_reason={fault_reason}, handling_method={handling_method}, "
                f"handler={handler}, delete_list={delete_list}, "
                f"attachments数量={len(attachments) if attachments else 0}")
    
    logger.info(f"收到更新问题单信息请求，问题单ID: {ticket_id}，当前用户: {current_user.id}")
    try:
        # 解析delete_list
        delete_list_ids = []
        if delete_list:
            try:
                delete_list_ids = json.loads(delete_list)
                if not isinstance(delete_list_ids, list):
                    raise ValueError("delete_list must be a list")
                delete_list_ids = [int(id) for id in delete_list_ids]
            except (json.JSONDecodeError, ValueError) as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid delete_list format: {str(e)}"
                )

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
        ticket.address = address
        ticket.fault_phenomenon = fault_phenomenon
        ticket.fault_reason = fault_reason
        ticket.handling_method = handling_method
        ticket.handler = handler or current_user.username
        ticket.user_id = current_user.id

        # 处理需要删除的附件
        if delete_list_ids:
            logger.info(f"需要删除的附件ID列表: {delete_list_ids}")
            # 查询需要删除的附件关联
            stmt = select(TicketAttachmentLink).where(
                TicketAttachmentLink.ticket_id == ticket_id,
                TicketAttachmentLink.attachment_id.in_(delete_list_ids)
            )
            result = await db.execute(stmt)
            delete_links = result.scalars().all()
            
            if delete_links:
                # 获取需要删除的附件ID
                delete_attachment_ids = [link.attachment_id for link in delete_links]
                
                # 查询需要删除的附件
                stmt = select(Attachment).where(Attachment.id.in_(delete_attachment_ids))
                result = await db.execute(stmt)
                delete_attachments = result.scalars().all()
                
                # 删除附件文件
                for attachment in delete_attachments:
                    try:
                        if os.path.exists(attachment.file_path):
                            os.remove(attachment.file_path)
                    except Exception as e:
                        logger.error(f"删除附件文件失败: {str(e)}")
                
                # 删除附件关联和附件记录
                for link in delete_links:
                    await db.delete(link)
                for attachment in delete_attachments:
                    await db.delete(attachment)

        # 处理新上传的附件
        if attachments:
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
            "address": ticket.address,
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
