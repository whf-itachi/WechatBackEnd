from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form, Body
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import FileResponse
from app.db_services.database import get_db
from app.dependencies.BM_auth import bm_verify_token
from app.services.baiLian_service import async_delete_rag_document
from app.services.ticket_service import delete_ticket_service
from app.schemas.ticket_schema import TicketResponse, TicketCreate
from app.models.user import User
from typing import List, Optional
from app.logger import get_logger
import os
from datetime import datetime, timezone
from app.models.ticket import Ticket, Attachment, TicketAttachmentLink
from sqlalchemy import select
import json

from app.services.user_service import get_user_by_id


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
async def create_ticket_json(
        ticket_data: TicketCreate = Body(...),
        db: AsyncSession = Depends(get_db),
        token_payload: dict = Depends(bm_verify_token)
):
    """创建工单（接收 JSON）"""
    logger.info(f"开始创建工单: {ticket_data.device_model}")
    try:
        current_user = await get_user_by_id(db, token_payload.get("user_id"))

        # 创建工单对象
        ticket = Ticket(
            device_model=ticket_data.device_model,
            customer=ticket_data.customer,
            fault_phenomenon=ticket_data.fault_phenomenon,
            fault_reason=ticket_data.fault_reason,
            handling_method=ticket_data.handling_method,
            handler=ticket_data.handler or current_user.name,
            user_id=current_user.id
        )
        db.add(ticket)
        await db.commit()
        logger.info(f"工单创建成功: {ticket.id}")
        return {"message": "工单创建成功", "ticket_id": ticket.id}

    except Exception as e:
        logger.error(f"工单创建失败: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="工单创建失败"
        )



# 查询所有问题单
@router.get("/list")
async def get_tickets(
        page: int = 1,
        pageSize: int = 10,
        device_model: str= "",
        creator: str= "",
        db: AsyncSession = Depends(get_db),
        token_payload: dict = Depends(bm_verify_token)
):
    """查询所有问题单"""
    current_user = await get_user_by_id(db, token_payload.get("user_id"))
    logger.info(f"查询所有问题单 请求，当前用户: {current_user.id}")
    try:
        # 构建查询条件
        query = select(Ticket)

        if device_model:
            query = query.where(Ticket.device_model.ilike(f"%{device_model}%"))

        if creator:
            # 通过 user_id 获取 creator 对应的用户
            creator_user = await db.execute(select(User).where(User.name.ilike(f"%{creator}%")))
            creator_user = creator_user.scalars().all()
            if creator_user:
                user_ids = [user.id for user in creator_user]
                query = query.where(Ticket.user_id.in_(user_ids))

        # 获取总工单数
        total_count_result = await db.execute(query)
        total_count = len(total_count_result.scalars().all())

        # 查询分页工单
        query = query.offset((page - 1) * pageSize).limit(pageSize)
        result = await db.execute(query)
        tickets = result.scalars().all()

        # 提取所有 user_id
        user_ids = list(set(ticket.user_id for ticket in tickets if ticket.user_id))

        # 批量查询用户信息
        user_map = {}
        if user_ids:
            user_stmt = select(User).where(User.id.in_(user_ids))
            user_result = await db.execute(user_stmt)
            users = user_result.scalars().all()
            user_map = {user.id: user.name for user in users}

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
                "creator": user_map.get(ticket.user_id, ""),  # 新增字段
                "create_at": ticket.create_at
            }

            print(ticket_dict)
            response_data.append(ticket_dict)

        logger.info(f"成功获取问题单列表，共 {len(tickets)} 条记录")
        # 返回分页数据和总记录数
        return {"total_count": total_count, "tickets": response_data}
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
        token_payload: dict = Depends(bm_verify_token)
):
    """根据ID获取问题单信息"""
    current_user = await get_user_by_id(db, token_payload.get("user_id"))
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
        delete_list: Optional[str] = Form(None),  # 修改为字符串类型，前端传入JSON字符串
        attachments: List[UploadFile] = File(None),
        db: AsyncSession = Depends(get_db),
        token_payload: dict = Depends(bm_verify_token)
):
    """更新问题单信息"""
    # 打印入参
    logger.info(f"更新问题单入参: ticket_id={ticket_id}, device_model={device_model}, "
                f"customer={customer}, fault_phenomenon={fault_phenomenon}, "
                f"fault_reason={fault_reason}, handling_method={handling_method}, "
                f"handler={handler}, delete_list={delete_list}, "
                f"attachments数量={len(attachments) if attachments else 0}")
    current_user = await get_user_by_id(db, token_payload.get("user_id"))
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
        token_payload: dict = Depends(bm_verify_token)
):
    """删除问题单"""
    current_user = await get_user_by_id(db, token_payload.get("user_id"))
    logger.info(f"收到删除问题单请求，问题单ID: {ticket_id}，当前用户: {current_user.id}")
    try:
        result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
        db_ticket = result.scalar_one_or_none()
        if not db_ticket:
            raise HTTPException(status_code=404, detail="问题单不存在")
        print(db_ticket.file_id)
        if db_ticket.file_id:
            await async_delete_rag_document(db, file_id=db_ticket.file_id, f_type="ticket")
        else:
            await db.delete(db_ticket)
            await db.commit()

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


@router.get("/files/preview")
def preview_file(file_path: str):
    # 安全检查（防止任意路径访问）
    target_path = os.path.abspath(file_path)
    if not os.path.isfile(target_path):
        raise HTTPException(status_code=404, detail="非法访问路径")

    return FileResponse(target_path)

