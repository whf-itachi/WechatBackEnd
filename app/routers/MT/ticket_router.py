from fastapi.responses import FileResponse
from fastapi import BackgroundTasks
from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db_services.database import get_db
from app.services.baiLian_service import process_full_rag_upload
from app.services.ticket_service import delete_attachment_by_id, handle_attachment_files
from app.schemas.ticket_schema import *
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.logger import get_logger
import os
from app.models.ticket import *
from sqlalchemy import select, cast, String, or_
import json

from app.utils.ali.BaiLianRAG import BaiLian

router = APIRouter()
logger = get_logger('ticket_router')

# 查询所有编号设备
@router.get("/devices", response_model=List[DeviceResponse])
async def get_devices(
    keyword: Optional[str] = Query(None, description="设备名称模糊匹配关键字"),
    db: AsyncSession = Depends(get_db)
):
    """
    查询所有设备，可通过 keyword 进行模糊匹配
    """
    try:
        stmt = select(DeviceTable)
        if keyword:
            # 模糊匹配 device_name 字段
            stmt = stmt.where(DeviceTable.device_name.ilike(f"%{keyword}%"))

        result = await db.execute(stmt)
        devices = result.scalars().all()
        return devices

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询设备失败: {str(e)}"
        )


@router.get("/devices/model_list", summary="获取设备型号列表及其设备")
async def get_list_device_models_with_devices(db: AsyncSession = Depends(get_db)):
    """
    查询所有设备型号，并包含每个型号下的设备列表
    返回结构：型号 -> 设备数组
    """
    try:
        # 使用 joinedload 模拟（手动 join 查询）
        result = await db.execute(
            select(DeviceModel)
            .options(selectinload(DeviceModel.devices))  # 推荐：用于一对多
        )
        models = result.unique().scalars().all()

        # 手动序列化为 dict 结构（避免 ORM 模型直接暴露）
        data = []
        for model in models:
            data.append({
                "device_model": model.device_model,
                "devices": [
                    {
                        "id": d.id,
                        "device_name": d.device_name,
                        "device_type": d.device_type
                    }
                    for d in model.devices  # 注意：这里 devices 是 relationship
                ]
            })

        return data

    except Exception as e:
        logger.error(f"查询设备型号及设备列表失败: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"查询设备数据失败: {str(e)}"
        )


# 根据设备id查询设备详情
@router.get("/devices/{device_id}", response_model=DeviceDetailResponse)
async def get_device_detail(
        device_id: int,
        db: AsyncSession = Depends(get_db)
):
    """
    根据设备ID查询设备详情，包括型号、客户和工厂信息
    """
    try:
        # 构建查询，关联设备型号、工厂和客户信息
        stmt = (
            select(
                DeviceTable,
                DeviceModel.id.label('model_id'),
                DeviceModel.device_model,
                Factory.id.label('factory_id'),
                Factory.factory_name,
                Factory.address,
                Customer.id.label('customer_id'),
                Customer.customer.label('customer_name'),
                Customer.contact_info,
                Customer.email
            )
            .join(DeviceModel, DeviceTable.device_model_id == DeviceModel.id)
            .outerjoin(Factory, DeviceTable.factory_id == Factory.id)
            .outerjoin(Customer, Factory.customer_id == Customer.id)
            .where(DeviceTable.id == device_id)
        )

        result = await db.execute(stmt)
        device_data = result.first()

        if not device_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"设备ID为 {device_id} 的设备不存在"
            )

        # 组装返回数据
        device, model_id, device_model, factory_id, factory_name, address,customer_id, customer_name, contact_info, email = device_data

        return {
            "id": device.id,
            "device_name": device.device_name,
            "device_type": device.device_type,
            "processing_range": device.processing_range,
            "remarks": device.remarks,
            "created_at": device.created_at,
            "model_id": model_id,
            "device_model": device_model,
            "factory_id": factory_id,
            "factory_name": factory_name,
            "address": address,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "contact_info": contact_info,
            "email": email
        }

    except HTTPException as e:
        # 重新抛出404异常
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询设备详情失败: {str(e)}"
        )

# 创建工单
@router.post("/submit")
async def create_ticket(
    background_tasks: BackgroundTasks,
    device_id: int = Form(...),  # 必填
    fault_phenomenon: str = Form(...),
    fault_reason: Optional[str] = Form(None),
    handling_method: Optional[str] = Form(None),
    handler: Optional[str] = Form(None),
    attachments: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    创建工单（仅支持通过 device_id 关联已有设备）
    前端必须先选择设备（可展示：设备编号 + 型号 + 客户 + 地址）
    """
    logger.info(f"用户 {current_user.name} 请求创建工单，关联设备 ID: {device_id}")

    try:
        # ========== 1. 验证设备是否存在 ==========
        result = await db.execute(
            select(DeviceTable)
            .options(selectinload(DeviceTable.model),
                selectinload(DeviceTable.factory).selectinload(Factory.customer)
            )
            .where(DeviceTable.id == device_id)
        )
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404,detail="设备不存在，请检查设备编号")

        # ========== 2. 创建工单 ==========
        ticket = Ticket(
            user_id=current_user.id,
            device_id=device.id,
            fault_phenomenon=fault_phenomenon,
            fault_reason=fault_reason,
            handling_method=handling_method,
            handler=handler or current_user.username,
            status=0  # 默认为“待处理”
        )
        db.add(ticket)
        await db.flush()  # 获取 ticket.id

        # ========== 3. 处理附件（如果有） ==========
        if attachments and len(attachments) > 0:
            try:
                await handle_attachment_files(db, ticket.id, attachments)
            except Exception as e:
                logger.error(f"工单 {ticket.id} 附件保存失败: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=400,
                    detail="附件上传失败，请检查文件格式或大小"
                )

        await db.commit()
        logger.info(f"工单创建成功: ticket_id={ticket.id}, device_id={device.id}")

        # ========== 4. 异步构建知识库文档 ==========
        # 提取关键信息用于 RAG
        row_data = {
            "id": ticket.id,
            "device_name": device.device_name,
            "device_model": device.model.device_model if device.model else "未知型号",
            "customer": device.factory.customer.customer if device.factory and device.factory.customer else "未知客户",
            "factory_address": device.factory.address if device.factory else "地址未填写",
            "fault_phenomenon": ticket.fault_phenomenon,
            "handling_method": ticket.handling_method,
            "handler": ticket.handler,
            "create_at": ticket.create_at.isoformat()
        }
        content = '\n'.join(f'{k}: {v}' for k, v in row_data.items())
        file_bytes = content.encode('utf-8')
        dict_data = {
            "id": ticket.id,
            "f_type": "ticket",
            "file_name": f"ticket_{ticket.id}.txt"
        }
        background_tasks.add_task(process_full_rag_upload, file_bytes, dict_data)

        return {"message": "工单创建成功", "ticket_id": ticket.id, "device_name": device.device_name}
    except Exception as e:
        logger.error(f"创建工单时发生未预期错误: {str(e)}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500,detail={"message": "工单创建失败", "error": "系统内部错误"})


# 查询所有工单（在移动端接口中其实并没有使用到）
@router.get("/list", response_model=List[TicketResponse])
async def get_tickets(
    page: int = 1,
    pageSize: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """查询所有工单"""
    logger.info(f"收到获取工单列表请求，当前用户: {current_user.id}")
    try:
        # 查询工单
        stmt = select(Ticket).offset((page - 1) * pageSize).limit(pageSize)
        result = await db.execute(stmt)
        tickets = result.scalars().all()

        if not tickets:
            return []

        # 获取工单关联的 device_id
        device_ids = [ticket.device_id for ticket in tickets]

        # 查询所有设备信息
        stmt = (
            select(DeviceTable.id, DeviceModel.device_model, Factory.factory_name, Customer.customer)
            .join(DeviceModel, DeviceTable.device_model_id == DeviceModel.id)
            .join(Factory, DeviceTable.factory_id == Factory.id)
            .join(Customer, Factory.customer_id == Customer.id)
            .where(DeviceTable.id.in_(device_ids))
        )
        result = await db.execute(stmt)
        device_map = {row[0]: {"device_model": row[1], "factory_name": row[2], "customer": row[3]} for row in result}

        # 获取所有工单ID的附件
        ticket_ids = [ticket.id for ticket in tickets]
        attachments_map = {}
        if ticket_ids:
            stmt = select(TicketAttachmentLink.ticket_id, Attachment).join(
                Attachment, TicketAttachmentLink.attachment_id == Attachment.id
            ).where(TicketAttachmentLink.ticket_id.in_(ticket_ids))
            result = await db.execute(stmt)
            for row in result:
                ticket_id = row[0]
                attachment = row[1]
                if ticket_id not in attachments_map:
                    attachments_map[ticket_id] = []
                attachments_map[ticket_id].append({
                    "id": attachment.id,
                    "file_path": attachment.file_path,
                    "file_type": attachment.file_type,
                    "upload_time": attachment.upload_time,
                    "file_name": os.path.basename(attachment.file_path)
                })

        # 构建响应
        response_data = []
        for ticket in tickets:
            device_info = device_map.get(ticket.device_id, {})
            ticket_dict = {
                "id": ticket.id,
                "device_model": device_info.get("device_model"),
                "customer": device_info.get("customer"),
                "factory_name": device_info.get("factory_name"),
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

        logger.info(f"成功获取工单列表，共 {len(tickets)} 条记录")
        return response_data

    except HTTPException as e:
        logger.error(f"获取工单列表失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取工单列表失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询所有工单时发生错误: {str(e)}"
        )


# 查询当前用户的所有工单
@router.get("/my-tickets", response_model=List[TicketResponse])
async def get_my_tickets(
        page: int = Query(1, ge=1, description="页码，从1开始"),
        pageSize: int = Query(10, ge=1, le=100, description="每页数量，最大100"),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """查询当前用户的所有工单"""
    logger.info(f"收到获取当前用户工单列表请求，用户ID: {current_user.id}")
    try:
        # 查询当前用户的工单
        stmt = select(Ticket).where(
            Ticket.user_id == current_user.id
        ).order_by(Ticket.id.desc()).offset((page - 1) * pageSize).limit(pageSize)

        result = await db.execute(stmt)
        tickets = result.scalars().all()

        if not tickets:
            return []

        # 获取工单关联的 device_id
        device_ids = [ticket.device_id for ticket in tickets if ticket.device_id]

        # 查询设备、型号、客户和工厂信息
        device_map = {}
        if device_ids:
            stmt = (
                select(DeviceTable.id,DeviceModel.device_model,Factory.factory_name,Factory.address,Customer.customer)
                .join(DeviceModel, DeviceTable.device_model_id == DeviceModel.id)
                .join(Factory, DeviceTable.factory_id == Factory.id)
                .join(Customer, Factory.customer_id == Customer.id)
                .where(DeviceTable.id.in_(device_ids))
            )
            result = await db.execute(stmt)
            device_map = {
                row[0]: {
                    "device_model": row[1],
                    "factory_name": row[2],
                    "address": row[3],
                    "customer": row[4]
                }
                for row in result
            }

        # 查询所有工单的附件
        ticket_ids = [ticket.id for ticket in tickets]
        attachments_map = {}
        if ticket_ids:
            stmt = select(TicketAttachmentLink.ticket_id, Attachment).join(
                Attachment, TicketAttachmentLink.attachment_id == Attachment.id
            ).where(TicketAttachmentLink.ticket_id.in_(ticket_ids))
            result = await db.execute(stmt)
            for row in result:
                ticket_id = row[0]
                attachment = row[1]
                if ticket_id not in attachments_map:
                    attachments_map[ticket_id] = []
                attachments_map[ticket_id].append({
                    "id": attachment.id,
                    "file_path": attachment.file_path,
                    "file_type": attachment.file_type,
                    "upload_time": attachment.upload_time,
                    "file_name": attachment.file_name
                })

        # 构建响应
        response_data = []
        for ticket in tickets:
            device_info = device_map.get(ticket.device_id, {})
            ticket_dict = {
                "id": ticket.id,
                "device_model": device_info.get("device_model"),
                "customer": device_info.get("customer"),
                "factory_name": device_info.get("factory_name"),
                "address": device_info.get("address"),  # 使用工厂地址
                "fault_phenomenon": ticket.fault_phenomenon,
                "fault_reason": ticket.fault_reason,
                "handling_method": ticket.handling_method,
                "handler": ticket.handler,
                "user_id": ticket.user_id,
                "status": ticket.status,
                "create_at": ticket.create_at,
                "attachments": attachments_map.get(ticket.id, [])
            }
            response_data.append(ticket_dict)

        logger.info(f"成功获取当前用户工单列表，共 {len(tickets)} 条记录")
        return response_data

    except HTTPException as e:
        logger.error(f"获取当前用户工单列表失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"获取当前用户工单列表失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询当前用户工单时发生错误: {str(e)}"
        )


# 根据关键词搜索工单（全字段，无分页）
@router.get("/search", response_model=List[dict])
async def search_all_fields(
    query: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据关键词搜索工单（全字段，无分页）"""
    logger.info(f"收到搜索工单请求，关键词: {query}，当前用户: {current_user.id}")
    try:
        like_pattern = f"%{query}%"

        # 构建查询，直接 join 所需表，避免异步环境下 lazy load
        stmt = (
            select(
                Ticket.id,
                Ticket.device_id,
                Ticket.fault_phenomenon,
                Ticket.fault_reason,
                Ticket.handling_method,
                Ticket.handler,
                Ticket.user_id,
                Ticket.status,
                Ticket.create_at,
                DeviceModel.device_model.label("device_model"),
                Factory.factory_name.label("factory_name"),
                Factory.address.label("factory_address"),
                Customer.customer.label("customer_name")
            )
            .join(DeviceTable, Ticket.device_id == DeviceTable.id, isouter=True)
            .join(DeviceModel, DeviceTable.device_model_id == DeviceModel.id, isouter=True)
            .join(Factory, DeviceTable.factory_id == Factory.id, isouter=True)
            .join(Customer, Factory.customer_id == Customer.id, isouter=True)
            .where(
                Ticket.user_id == current_user.id,
                or_(
                    Ticket.fault_phenomenon.ilike(like_pattern),
                    Ticket.fault_reason.ilike(like_pattern),
                    Ticket.handling_method.ilike(like_pattern),
                    Ticket.handler.ilike(like_pattern),
                    cast(Ticket.status, String).ilike(like_pattern),
                    DeviceModel.device_model.ilike(like_pattern),
                    Factory.factory_name.ilike(like_pattern),
                    Factory.address.ilike(like_pattern),
                    Customer.customer.ilike(like_pattern)
                )
            )
        )

        result = await db.execute(stmt)
        tickets = result.all()

        if not tickets:
            return []

        # 获取工单ID
        ticket_ids = [t.id for t in tickets]

        # 查询附件
        attachments_map = {}
        if ticket_ids:
            stmt = (
                select(TicketAttachmentLink.ticket_id, Attachment)
                .join(Attachment, TicketAttachmentLink.attachment_id == Attachment.id)
                .where(TicketAttachmentLink.ticket_id.in_(ticket_ids))
            )
            result = await db.execute(stmt)
            for ticket_id, attachment in result:
                attachments_map.setdefault(ticket_id, []).append({
                    "id": attachment.id,
                    "file_path": attachment.file_path,
                    "file_name": os.path.basename(attachment.file_path),
                    "file_type": attachment.file_type,
                    "upload_time": attachment.upload_time
                })

        # 构建响应
        response_data = []
        for t in tickets:
            response_data.append({
                "id": t.id,
                "device_model": t.device_model,
                "customer": t.customer_name,
                "address": t.factory_address,
                "fault_phenomenon": t.fault_phenomenon,
                "fault_reason": t.fault_reason,
                "handling_method": t.handling_method,
                "handler": t.handler,
                "user_id": t.user_id,
                "status": t.status,
                "create_at": t.create_at,
                "attachments": attachments_map.get(t.id, [])
            })

        logger.info(f"成功搜索工单，共 {len(response_data)} 条记录")
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


# 根据工单 id 查询工单信息
@router.get("/{ticket_id}", response_model=dict)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据ID获取工单信息（包含设备、型号、客户、工厂及附件）"""
    logger.info(f"收到获取工单信息请求，工单ID: {ticket_id}，当前用户: {current_user.id}")
    try:
        # 查询工单 + 设备 + 型号 + 工厂 + 客户
        stmt = (
            select(
                Ticket.id,
                Ticket.device_id,
                Ticket.user_id,
                Ticket.fault_phenomenon,
                Ticket.fault_reason,
                Ticket.handling_method,
                Ticket.handler,
                Ticket.status,
                Ticket.create_at,
                DeviceModel.device_model.label("device_model"),
                Customer.customer.label("customer_name"),
                Factory.factory_name.label("factory_name"),
                Factory.address.label("factory_address")
            )
            .join(DeviceTable, Ticket.device_id == DeviceTable.id, isouter=True)
            .join(DeviceModel, DeviceTable.device_model_id == DeviceModel.id, isouter=True)
            .join(Factory, DeviceTable.factory_id == Factory.id, isouter=True)
            .join(Customer, Factory.customer_id == Customer.id, isouter=True)
            .where(Ticket.id == ticket_id)
        )

        result = await db.execute(stmt)
        ticket = result.first()

        if not ticket:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该工单")

        # 查询附件
        stmt_attach = (
            select(TicketAttachmentLink.ticket_id, Attachment)
            .join(Attachment, TicketAttachmentLink.attachment_id == Attachment.id)
            .where(TicketAttachmentLink.ticket_id == ticket_id)
        )
        result_attach = await db.execute(stmt_attach)
        attachments = [
            {
                "id": att.id,
                "file_path": att.file_path,
                "file_name": att.file_name,
                "file_type": att.file_type,
                "upload_time": att.upload_time
            }
            for _, att in result_attach
        ]

        response_data = {
            "id": ticket.id,
            "device_id": ticket.device_id,
            "user_id": ticket.user_id,
            "device_model": ticket.device_model,
            "customer": ticket.customer_name,
            "factory": ticket.factory_name,
            "address": ticket.factory_address,
            "fault_phenomenon": ticket.fault_phenomenon,
            "fault_reason": ticket.fault_reason,
            "handling_method": ticket.handling_method,
            "handler": ticket.handler,
            "status": ticket.status,
            "create_at": ticket.create_at,
            "attachments": attachments
        }

        logger.info(f"成功获取工单信息: {ticket.id}")
        return response_data

    except HTTPException as e:
        logger.error(f"获取工单信息失败 - HTTP异常: {str(e)}")
        raise e
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
    device_id: int = Form(...),  # 只需要传设备ID
    fault_phenomenon: str = Form(...),
    fault_reason: Optional[str] = Form(None),
    handling_method: Optional[str] = Form(None),
    handler: Optional[str] = Form(None),
    delete_list: Optional[str] = Form(None),  # 前端传入JSON字符串
    attachments: List[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新工单信息"""
    logger.info(f"更新工单入参: ticket_id={ticket_id}, device_id={device_id}, "
                f"fault_phenomenon={fault_phenomenon}, fault_reason={fault_reason}, "
                f"handling_method={handling_method}, handler={handler}, "
                f"delete_list={delete_list}, attachments数量={len(attachments) if attachments else 0}")

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

        # 获取当前工单
        stmt = select(Ticket).where(Ticket.id == ticket_id)
        result = await db.execute(stmt)
        ticket = result.scalar_one_or_none()
        if not ticket:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到该工单")

        # 查询设备信息
        stmt = (
            select(DeviceTable)
            .where(DeviceTable.id == device_id)
            .options(selectinload(DeviceTable.model))  # 预加载设备型号
            .options(selectinload(DeviceTable.factory).selectinload(Factory.customer))  # 预加载工厂及客户
        )
        result = await db.execute(stmt)
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到对应设备")

        # 更新工单信息
        ticket.device_id = device.id
        ticket.fault_phenomenon = fault_phenomenon
        ticket.fault_reason = fault_reason
        ticket.handling_method = handling_method
        ticket.handler = handler or current_user.username
        ticket.user_id = current_user.id

        # 删除附件
        if delete_list_ids:
            for attachment_id in delete_list_ids:
                await delete_attachment_by_id(db, attachment_id)

        # 新附件处理
        if attachments:
            await handle_attachment_files(db, ticket.id, attachments)

        # 提交事务
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="数据库提交失败")

        # 查询附件
        stmt = select(Attachment).join(
            TicketAttachmentLink,
            Attachment.id == TicketAttachmentLink.attachment_id
        ).where(TicketAttachmentLink.ticket_id == ticket_id)
        result = await db.execute(stmt)
        attachments_list = result.scalars().all()
        ticket_attachments = [
            {
                "id": att.id,
                "file_path": att.file_path,
                "file_type": att.file_type,
                "upload_time": att.upload_time,
                "file_name": att.file_name
            } for att in attachments_list
        ]

        # 删除大模型文档
        if ticket.file_id:
            try:
                bai_lian = BaiLian()
                bai_lian.delete_rag_document(ticket.file_id)  # 删除文档
                bai_lian.delete_rag_index(ticket.file_id)  # 删除知识库索引文档
            except Exception as e:
                logger.error(f"移动端修改工单信息，删除大模型文档报错：{e}")

        # 异步处理大模型文档
        row_data = ticket.model_dump()
        content = '\n'.join(f'{key}: {value}' for key, value in row_data.items())
        file_bytes = content.encode('utf-8')
        dict_data = {"id": ticket.id, "f_type": "ticket", "file_name": f"ticket_{ticket.id}.txt"}
        background_tasks.add_task(process_full_rag_upload, file_bytes, dict_data)

        # 返回数据
        response_data = {
            "id": ticket.id,
            "device_id": ticket.device_id,
            "device_model": device.model.device_model if device.model else None,
            "customer": device.factory.customer.customer if device.factory and device.factory.customer else None,
            "address": device.factory.address if device.factory else None,
            "fault_phenomenon": ticket.fault_phenomenon,
            "fault_reason": ticket.fault_reason,
            "handling_method": ticket.handling_method,
            "handler": ticket.handler,
            "user_id": ticket.user_id,
            "status": ticket.status,
            "create_at": ticket.create_at,
            "attachments": ticket_attachments
        }

        logger.info(f"成功更新工单信息: {ticket.id}")
        return response_data

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/attachment/{attachment_id}/preview")
async def preview_attachment(attachment_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Attachment).where(Attachment.id == attachment_id)
    )
    attachment = result.scalars().first()

    if not attachment:
        raise HTTPException(status_code=404, detail="附件不存在")

    file_path = os.path.join(attachment.file_path, attachment.file_name)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=attachment.file_path,
        filename=attachment.file_name,
        media_type=attachment.file_type or "application/octet-stream",
        headers={"Content-Disposition": f"inline; filename={attachment.file_name}"}
    )
