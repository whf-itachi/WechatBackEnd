from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form, Body, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import FileResponse
from sqlalchemy.orm import selectinload

from app.db_services.database import get_db
from app.dependencies.BM_auth import bm_verify_token
from app.services.baiLian_service import process_full_rag_upload
from app.schemas.ticket_schema import TicketResponse, TicketCreate
from app.models.user import User
from app.logger import get_logger
import os
from app.models.ticket import *
from sqlalchemy import select, func
import json

from app.services.ticket_service import delete_attachment_by_id, delete_ticket_service, handle_attachment_files
from app.services.user_service import get_user_by_id
from app.utils.ali.BaiLianRAG import BaiLian

router = APIRouter()
logger = get_logger('ticket_router')


# 创建工单
@router.post("/submit")
async def create_ticket_json(
    background_tasks: BackgroundTasks,
    ticket_data: TicketCreate = Body(...),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token)
):
    """创建工单（接收 JSON）"""
    logger.info(f"开始创建工单: 设备ID={ticket_data.device_id}")
    try:
        current_user = await get_user_by_id(db, token_payload.get("user_id"))

        # 查询设备是否存在
        stmt = select(DeviceTable).where(DeviceTable.id == ticket_data.device_id)
        result = await db.execute(stmt)
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=400, detail="设备不存在")

        # 创建工单对象
        ticket = Ticket(
            device_id=ticket_data.device_id,
            fault_phenomenon=ticket_data.fault_phenomenon,
            fault_reason=ticket_data.fault_reason,
            handling_method=ticket_data.handling_method,
            handler=ticket_data.handler or current_user.name,
            user_id=current_user.id
        )
        db.add(ticket)
        await db.commit()
        await db.refresh(ticket)

        # 可选：RAG 文档生成（可继续使用 ticket.id 生成内容）
        row_data = ticket.model_dump()
        row_data.update({
            "device_name": device.device_name,
            "device_model": device.model.device_model,
            "customer": device.factory.customer.customer,
            "address": device.factory.address,
        })
        content = '\n'.join(f'{key}: {value}' for key, value in row_data.items())
        file_bytes = content.encode('utf-8')
        dict_data = {
            "id": ticket.id,
            "f_type": "ticket",
            "file_name": f"ticket_{ticket.id}.txt"
        }

        background_tasks.add_task(process_full_rag_upload, file_bytes, dict_data)
        logger.info(f"工单创建成功: {ticket.id}")
        return {"message": "工单创建成功", "ticket_id": ticket.id}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"工单创建失败: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail="工单创建失败")



# 查询所有工单（分页查询）
@router.get("/list")
async def get_tickets(
    page: int = 1,
    page_size: int = 10,
    device_model: str = "",
    creator: str = "",
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token),
):
    """查询所有工单（支持分页、按设备型号、创建人过滤）"""
    try:
        current_user = await get_user_by_id(db, token_payload.get("user_id"))
        logger.info(f"查询所有工单 请求，当前用户: {current_user.id}")
        base_query = (
            select(Ticket, User.name.label("creator_name"))
            .join(User, Ticket.user_id == User.id)
            .join(DeviceTable, Ticket.device_id == DeviceTable.id)
            .join(DeviceModel, DeviceTable.device_model_id == DeviceModel.id)
            .options(
                selectinload(Ticket.device).selectinload(DeviceTable.model),
                selectinload(Ticket.device).selectinload(DeviceTable.factory).selectinload(Factory.customer),
            )
        )

        # 过滤条件
        filters = []
        if device_model:
            filters.append(DeviceModel.device_model.ilike(f"%{device_model}%"))
        if creator:
            filters.append(User.name.ilike(f"%{creator}%"))
        if filters:
            base_query = base_query.where(*filters)

        # 统计总数
        count_query = (
            select(func.count(Ticket.id))
            .join(User, Ticket.user_id == User.id)
            .join(DeviceTable, Ticket.device_id == DeviceTable.id)
            .join(DeviceModel, DeviceTable.device_model_id == DeviceModel.id)
        )
        if filters:
            count_query = count_query.where(*filters)

        total_count = (await db.execute(count_query)).scalar_one()

        # 分页查询
        query = ( base_query.order_by(Ticket.create_at.desc()).offset((page - 1) * page_size).limit(page_size))

        result = await db.execute(query)
        rows = result.all()

        # 构建响应
        response_data = []
        for ticket, creator_name in rows:
            device = ticket.device
            model = device.model
            factory = device.factory
            customer = factory.customer if factory else None

            response_data.append({
                "id": ticket.id,
                "device_id": device.id,
                "device_name": device.device_name,
                "device_model": model.device_model if model else "未知",
                "customer": customer.customer if customer else "未知",
                "address": factory.address if factory else None,
                "fault_phenomenon": ticket.fault_phenomenon,
                "fault_reason": ticket.fault_reason,
                "handling_method": ticket.handling_method,
                "handler": ticket.handler,
                "user_id": ticket.user_id,
                "status": ticket.status,
                "creator": creator_name or "未知",
                "create_at": ticket.create_at,
            })

        logger.info(f"成功获取工单列表，共 {len(response_data)} 条记录")
        return {"total_count": total_count, "tickets": response_data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取工单列表失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询所有工单时发生错误: {str(e)}",
        )


# 根据工单 id 查询工单信息
@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token)
):
    """根据ID获取工单信息"""
    current_user = await get_user_by_id(db, token_payload.get("user_id"))
    logger.info(f"收到获取工单信息请求，工单ID: {ticket_id}，当前用户: {current_user.id}")

    try:
        # 一次性加载工单 + 设备 + 型号 + 客户 + 附件
        stmt = (select(Ticket).where(Ticket.id == ticket_id)
                .options(
                selectinload(Ticket.device).selectinload(DeviceTable.model),
                selectinload(Ticket.device).selectinload(DeviceTable.factory).selectinload(Factory.customer),
                selectinload(Ticket.attachments)
                )
            )

        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()

        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该工单"
            )

        # 处理附件
        ticket_attachments = [
            {
                "id": att.id,
                "file_path": att.file_path,
                "file_type": att.file_type,
                "upload_time": att.upload_time,
                "file_name": att.file_name
            }
            for att in ticket.attachments
        ]

        # 关联字段安全取值
        device = ticket.device
        model = device.model if device else None
        factory = device.factory if device else None
        customer = factory.customer if factory else None

        # 构建响应
        response_data = {
            "id": ticket.id,
            "device_model": model.device_model if model else None,
            "address": factory.address if factory else None,
            "customer": customer.customer if customer else None,
            "fault_phenomenon": ticket.fault_phenomenon,
            "fault_reason": ticket.fault_reason,
            "handling_method": ticket.handling_method,
            "handler": ticket.handler,
            "user_id": ticket.user_id,
            "status": ticket.status,
            "create_at": ticket.create_at,
            "attachments": ticket_attachments
        }

        logger.info(f"成功获取工单信息: {ticket.id}")
        return response_data

    except HTTPException as e:
        logger.error(f"获取工单信息失败 - HTTP异常: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"获取工单信息失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询工单信息时发生错误: {str(e)}"
        )



# 根据工单 id 修改工单信息
@router.put("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(
    background_tasks: BackgroundTasks,
    ticket_id: int,
    fault_phenomenon: str = Form(...),
    fault_reason: Optional[str] = Form(None),
    handling_method: Optional[str] = Form(None),
    handler: Optional[str] = Form(None),
    delete_list: Optional[str] = Form(None),  # JSON字符串
    attachments: Optional[List[UploadFile]] = File(None),
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token)
):
    """
    更新工单信息：
    - 修改工单字段
    - 删除指定附件
    - 新增附件
    - 更新大模型知识库文档
    """
    logger.info(
        "更新工单: ticket_id=%s, fault_phenomenon=%s, "
        "fault_reason=%s, handling_method=%s, handler=%s, delete_list=%s, 附件数=%s",
        ticket_id, fault_phenomenon, fault_reason, handling_method, handler, delete_list,
        len(attachments) if attachments else 0
    )

    current_user = await get_user_by_id(db, token_payload.get("user_id"))

    # 解析 delete_list
    delete_list_ids: List[int] = []
    if delete_list:
        try:
            parsed = json.loads(delete_list)
            if not isinstance(parsed, list):
                raise ValueError("delete_list 必须是列表")
            delete_list_ids = [int(x) for x in parsed]
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"delete_list 参数错误: {e}"
            )

    # 查询工单
    ticket = await db.scalar(select(Ticket).where(Ticket.id == ticket_id))
    if not ticket:
        raise HTTPException(status_code=404, detail="未找到该工单")

    # 更新工单基本信息
    ticket.fault_phenomenon = fault_phenomenon
    ticket.fault_reason = fault_reason
    ticket.handling_method = handling_method
    ticket.handler = handler or current_user.username
    ticket.user_id = current_user.id

    # 删除附件
    if delete_list_ids:
        for att_id in delete_list_ids:
            try:
                await delete_attachment_by_id(db, att_id)
            except Exception as e:
                logger.error("删除附件失败 id=%s: %s", att_id, e, exc_info=True)
                raise HTTPException(status_code=400, detail=f"删除附件失败: {e}")

    # 新增附件
    if attachments:
        try:
            await handle_attachment_files(db, ticket.id, attachments)
        except Exception as e:
            logger.error("附件保存出错: %s", e, exc_info=True)
            raise HTTPException(status_code=400, detail="附件上传失败")

    # 提交数据库变更
    try:
        await db.commit()
    except Exception as e:
        logger.error("更新工单提交失败: %s", e, exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail="数据库提交失败")

    # 查询最新附件信息
    attachment_rows = await db.scalars(
        select(Attachment)
        .join(TicketAttachmentLink, Attachment.id == TicketAttachmentLink.attachment_id)
        .where(TicketAttachmentLink.ticket_id == ticket_id)
    )
    ticket_attachments = [
        {
            "id": att.id,
            "file_path": att.file_path,
            "file_type": att.file_type,
            "upload_time": att.upload_time,
            "file_name": att.file_name
        }
        for att in attachment_rows
    ]

    # 处理大模型文档
    try:
        if ticket.file_id:
            bai_lian = BaiLian()
            bai_lian.delete_rag_document(ticket.file_id)
            bai_lian.delete_rag_index(ticket.file_id)

        # 重新生成知识库文档
        row_data = ticket.model_dump()
        content = '\n'.join(f"{k}: {v}" for k, v in row_data.items())
        file_bytes = content.encode("utf-8")
        dict_data = {"id": ticket.id, "f_type": "ticket", "file_name": f"ticket_{ticket.id}.txt"}
        background_tasks.add_task(process_full_rag_upload, file_bytes, dict_data)
    except Exception as e:
        logger.error("更新工单时处理大模型文档失败: %s", e, exc_info=True)

    logger.info("工单更新成功 id=%s", ticket.id)
    return {
        "id": ticket.id,
        "device_model": "",
        "customer": "",
        "address": "",
        "status": 0,
        "fault_phenomenon": ticket.fault_phenomenon,
        "fault_reason": ticket.fault_reason,
        "handling_method": ticket.handling_method,
        "handler": ticket.handler,
        "user_id": ticket.user_id,
        "create_at": ticket.create_at,
        "attachments": ticket_attachments
    }


# 根据工单 id 删除工单
@router.delete("/{ticket_id}")
async def delete_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(bm_verify_token)
):
    """删除工单"""
    current_user = await get_user_by_id(db, token_payload.get("user_id"))
    logger.info(f"收到删除工单请求，工单ID: {ticket_id}，当前用户: {current_user.id}")

    try:
        # 调用删除逻辑
        result = await delete_ticket_service(db, ticket_id)
        if not result:
            raise HTTPException(status_code=404, detail="未找到该工单")

        await db.commit()
        logger.info(f"成功删除工单，工单ID: {ticket_id}")
        return {"message": "工单删除成功"}

    except HTTPException as e:
        logger.error(f"删除工单失败 - HTTP异常: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"删除工单失败 - 系统异常: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail="删除工单时发生错误")



@router.get("/files/preview")
def preview_file(file_path: str):
    # 安全检查（防止任意路径访问）
    target_path = os.path.abspath(file_path)
    if not os.path.isfile(target_path):
        raise HTTPException(status_code=404, detail="非法访问路径")

    return FileResponse(target_path)


@router.get("/attachment/{attachment_id}/preview")
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