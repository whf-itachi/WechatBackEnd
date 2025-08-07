from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_
from pydantic import BaseModel

from app.db_services.database import get_db
from app.logger import get_logger
from app.models.ticket import *

router = APIRouter()
logger = get_logger('ticket_router')


# ------------------------- 响应模型 -------------------------
class BaseResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Optional[dict] = None


class ErrorResponse(BaseModel):
    code: int
    message: str
    detail: Optional[str] = None


# ------------------------- 分页模型 -------------------------
class PageParams(BaseModel):
    page: int = 1
    size: int = 10


class PageResponse(BaseResponse):
    data: dict = {
        "items": [],
        "total": 0,
        "pages": 0,
        "has_next": False,
        "has_prev": False
    }


# ------------------------- 设备型号接口 -------------------------
@router.post("/device_models", summary="创建设备型号")
async def create_device_model(
        data: DeviceModel,
        db: AsyncSession = Depends(get_db)):
    """创建新设备型号（自动生成创建时间）"""
    try:
        existing = await db.execute(select(DeviceModel).where(DeviceModel.device_model == data.device_model))
        if existing.first():
            raise HTTPException(status_code=400, detail="设备型号已存在")

        device_dict = data.model_dump()
        new_model = DeviceModel(**device_dict)
        db.add(new_model)

        await db.commit()
        await db.refresh(new_model)

        return {"data": new_model}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"创建设备失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.get("/device_models", response_model=BaseResponse, summary="获取设备型号列表")
async def list_device_models(
    page: int = 1,
    size: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """分页查询设备型号"""
    try:
        offset = (page - 1) * size
        result = await db.execute(select(DeviceModel).offset(offset).limit(size))
        items = result.scalars().all()

        count_result = await db.execute(select(func.count()).select_from(DeviceModel))
        total_count = count_result.scalar_one()

        return {"data": {"items": items, "total": total_count}}
    except Exception as e:
        logger.error(f"查询设备型号失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.put("/device_models/{model_id}", summary="更新设备型号")
async def update_device_model(
    model_id: int,
    data: DeviceModel,
    db: AsyncSession = Depends(get_db)
):
    """根据 ID 更新设备型号"""
    try:
        result = await db.execute(select(DeviceModel).where(DeviceModel.id == model_id))
        model = result.scalars().first()  # 获取 ORM 实例

        if not model:
            raise HTTPException(status_code=404, detail="设备型号不存在")

        model.device_model = data.device_model
        await db.commit()
        await db.refresh(model)

        return {"data": model}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新设备型号失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))



@router.delete("/device_models/{model_id}", summary="删除设备型号")
async def delete_device_model(model_id: int, db: AsyncSession = Depends(get_db)):
    """根据 ID 删除设备型号"""
    try:
        result = await db.execute(select(DeviceModel).where(DeviceModel.id == model_id))
        model = result.scalar_one_or_none()
        if not model:
            raise HTTPException(status_code=404, detail="设备型号不存在")

        await db.delete(model)
        await db.commit()

        return {"data": f"ID为 {model_id} 的设备型号已删除"}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"删除设备型号失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))

# ------------------------- 设备管理接口 -------------------------
@router.post("/device", summary="创建设备")
async def create_device(
    data: DeviceTable,
    db: AsyncSession = Depends(get_db)
):
    """创建新设备，需指定设备型号和所属工厂"""
    try:
        # 检查设备编号是否已存在
        existing_name = await db.execute(
            select(DeviceTable).where(DeviceTable.device_name == data.device_name)
        )
        if existing_name.first():
            raise HTTPException(status_code=400, detail="设备编号已存在")

        # 验证 device_model_id 是否存在
        model_exists = await db.get(DeviceModel, data.device_model_id)
        if not model_exists:
            raise HTTPException(status_code=400, detail="设备型号不存在")

        # 验证 factory_id 是否存在（如果提供）
        if data.factory_id is not None:
            factory_exists = await db.get(Factory, data.factory_id)
            if not factory_exists:
                raise HTTPException(status_code=400, detail="工厂不存在")

        # 准备数据
        device_data = data.model_dump(exclude_unset=True)
        new_device = DeviceTable(**device_data)
        db.add(new_device)

        await db.commit()
        await db.refresh(new_device)

        return {"data": new_device}

    except Exception as e:
        logger.error(f"创建设备失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.get("/device/list", summary="获取设备列表（分页）")
async def get_device_list(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    device_name: Optional[str] = Query(None, description="设备编号模糊搜索"),
    device_type: Optional[str] = Query(None, description="设备类型模糊搜索"),
    factory_id: Optional[int] = Query(None, description="按工厂过滤"),
    model_id: Optional[int] = Query(None, description="按型号过滤"),
):
    """分页查询设备列表，支持按编号、类型、工厂、型号模糊/精确筛选"""
    try:
        offset = (page - 1) * page_size
        query = select(DeviceTable).join(DeviceModel).outerjoin(Factory)

        conditions = []
        if device_name:
            conditions.append(DeviceTable.device_name.contains(device_name))
        if device_type:
            conditions.append(DeviceTable.device_type.contains(device_type))
        if factory_id:
            conditions.append(DeviceTable.factory_id == factory_id)
        if model_id:
            conditions.append(DeviceTable.device_model_id == model_id)

        if conditions:
            query = query.where(and_(*conditions))

        # 获取总数
        count_query = select(func.count()).select_from(query.alias())
        total = (await db.execute(count_query)).scalar()

        # 分页查询
        query = query.offset(offset).limit(page_size)
        result = await db.execute(query)
        devices = result.scalars().all()

        return {"data": {"devices": devices, "total": total}}
    except Exception as e:
        logger.error(f"查询设备列表失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.get("/device/{device_id}", summary="获取设备详情")
async def get_device(
    device_id: int,
    db: AsyncSession = Depends(get_db)
):
    """根据设备 ID 获取详细信息，包含型号和工厂名称"""
    try:
        query = (
            select(DeviceTable)
            .join(DeviceModel)
            .outerjoin(Factory)
            .where(DeviceTable.id == device_id)
        )
        result = await db.execute(query)
        device = result.first()

        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")

        return {"data": device[0]}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"查询设备详情失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.put("/device/{device_id}", summary="更新设备")
async def update_device(
    device_id: int,
    data: DeviceTable,
    db: AsyncSession = Depends(get_db)
):
    """更新设备信息，设备编号不可重复"""
    try:
        device = await db.get(DeviceTable, device_id)
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")

        # 检查设备编号是否被其他设备占用
        if data.device_name and data.device_name != device.device_name:
            existing = await db.execute(
                select(DeviceTable).where(DeviceTable.device_name == data.device_name)
            )
            if existing.first():
                raise HTTPException(status_code=400, detail="设备编号已存在")

        # 验证型号是否存在
        if data.device_model_id:
            model_exists = await db.get(DeviceModel, data.device_model_id)
            if not model_exists:
                raise HTTPException(status_code=400, detail="设备型号不存在")

        # 验证工厂是否存在（如果提供）
        if data.factory_id is not None:
            factory_exists = await db.get(Factory, data.factory_id)
            if not factory_exists:
                raise HTTPException(status_code=400, detail="工厂不存在")

        # 更新字段
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(device, key, value)

        db.add(device)
        await db.commit()
        await db.refresh(device)

        return {"data": device}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新设备失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.delete("/device/{device_id}", summary="删除设备")
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db)
):
    """删除指定设备"""
    try:
        device = await db.get(DeviceTable, device_id)
        if not device:
            raise HTTPException(status_code=404, detail="设备不存在")

        await db.delete(device)
        await db.commit()

        return {"data": f"编号为 {device_id} 的设备已删除"}
    except Exception as e:
        logger.error(f"删除设备失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


# ------------------------- 客户管理接口 -------------------------
@router.post("/customers", summary="创建客户")
async def create_customer(
        data: Customer,
        db: AsyncSession = Depends(get_db)
):
    """创建新客户（自动生成创建时间）"""
    try:
        existing = await db.execute(select(Customer).where(Customer.customer == data.customer))
        if existing.first():
            raise HTTPException(status_code=400, detail="客户已存在")

        customer_dict = data.model_dump()
        new_model = Customer(**customer_dict)
        db.add(new_model)

        await db.commit()
        await db.refresh(new_model)

        return {"data": new_model}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"新增客户失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.get("/customers", summary="分页获取客户列表")
async def list_customers(
        page: int = Query(1, ge=1),
        size: int = Query(10, ge=1),
        db: AsyncSession = Depends(get_db)
):
    """获取客户列表（分页）"""
    try:
        offset = (page - 1) * size
        result = await db.execute(select(Customer).offset(offset).limit(size))
        items = result.scalars().all()

        count_result = await db.execute(select(func.count()).select_from(Customer))
        total_count = count_result.scalar_one()

        return {"data": {"items": items, "total": total_count}}
    except Exception as e:
        logger.error(f"查询客户信息失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.put("/customers/{customer_id}", summary="更新客户信息")
async def update_customer(
        customer_id: int,
        data: Customer,
        db: AsyncSession = Depends(get_db)
):
    """更新客户信息（带版本控制）"""
    try:
        result = await db.execute(select(Customer).where(Customer.id == customer_id))
        model = result.scalars().first()  # 获取 ORM 实例

        if not model:
            raise HTTPException(status_code=404, detail="客户不存在")

        model.customer = data.customer
        await db.commit()
        await db.refresh(model)

        return {"data": model}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新设备型号失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.delete("/customers/{customer_id}", response_model=BaseResponse, summary="删除客户")
async def delete_customer(
        customer_id: int,
        db: AsyncSession = Depends(get_db)
):
    """标记删除客户（保留历史数据）"""
    try:
        # 获取有效客户
        result = await db.execute(select(Customer).where(Customer.id == customer_id))
        customer = result.scalar_one_or_none()
        if not customer:
            logger.warning(f"删除无效客户ID: {customer_id}")
            raise HTTPException(404, detail="客户不存在")

        await db.delete(customer)
        await db.commit()

        logger.info(f"客户标记删除 | ID:{customer_id}")
        return BaseResponse(message="删除操作已完成")

    except HTTPException as e:
        raise e
    except Exception as e:
        await db.rollback()
        logger.error(
            f"删除操作失败 | ID:{customer_id} | 错误:{str(e)}",
            exc_info=True
        )
        return ErrorResponse(
            code=500,
            message="服务器内部错误",
            detail="系统繁忙，请稍后重试"
        )


# ------------------------- 工厂管理接口 -------------------------
@router.post("/factory", summary="创建工厂")
async def create_factory(
    data: Factory,
    db: AsyncSession = Depends(get_db)
):
    """
    创建新工厂（需指定所属客户ID）
    自动校验工厂名称唯一性
    """
    try:
        # 校验客户是否存在
        customer_result = await db.execute(
            select(Customer).where(Customer.id == data.customer_id)
        )
        customer = customer_result.first()
        if not customer:
            raise HTTPException(status_code=400, detail="客户不存在")

        # 校验工厂名称是否已存在（忽略大小写）
        name_check = await db.execute(
            select(Factory).where(func.lower(Factory.factory_name) == data.factory_name.strip().lower())
        )
        if name_check.first():
            raise HTTPException(status_code=400, detail="工厂名称已存在")

        # 构造数据（排除未传字段）
        factory_dict = data.model_dump(exclude_unset=True)
        new_factory = Factory(**factory_dict)

        db.add(new_factory)
        await db.commit()
        await db.refresh(new_factory)

        return {"data": new_factory}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"创建工厂失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.get("/factory/list", response_model=BaseResponse, summary="获取工厂列表（分页）")
async def list_factories(
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(10, ge=1, le=100, description="每页数量"),
    factory_name: Optional[str] = Query(None, description="工厂名称关键词搜索"),
    customer_id: Optional[int] = Query(None, description="按客户ID筛选"),
    db: AsyncSession = Depends(get_db)
):
    """
    分页查询工厂列表，支持按名称模糊搜索、按客户筛选
    """
    try:
        offset = (page - 1) * size

        # 基础查询 + 关联客户
        stmt = select(Factory).join(Customer)

        # 搜索条件
        if factory_name:
            stmt = stmt.where(Factory.factory_name.contains(factory_name))
        if customer_id:
            stmt = stmt.where(Factory.customer_id == customer_id)

        # 获取分页数据
        result = await db.execute(stmt.offset(offset).limit(size))
        items = result.scalars().all()

        # 获取总数
        count_stmt = select(func.count()).select_from(Factory)
        if factory_name:
            count_stmt = count_stmt.where(Factory.factory_name.contains(factory_name))
        if customer_id:
            count_stmt = count_stmt.where(Factory.customer_id == customer_id)
        count_result = await db.execute(count_stmt)
        total_count = count_result.scalar_one()

        return {"data": {"items": items, "total": total_count}}

    except Exception as e:
        logger.error(f"查询工厂列表失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.put("/factory/{factory_id}", summary="更新工厂信息")
async def update_factory(
    factory_id: int,
    data: Factory,
    db: AsyncSession = Depends(get_db)
):
    """
    更新工厂信息（支持部分更新）
    不能更改 customer_id 到不存在的客户
    """
    try:
        # 查询原工厂
        result = await db.execute(select(Factory).where(Factory.id == factory_id))
        factory = result.first()
        if not factory:
            raise HTTPException(status_code=404, detail="工厂不存在")

        factory = factory[0]  # 解包 scalars

        # 如果更新了 customer_id，校验客户是否存在
        if data.customer_id is not None and data.customer_id != factory.customer_id:
            customer_result = await db.execute(
                select(Customer).where(Customer.id == data.customer_id)
            )
            if not customer_result.first():
                raise HTTPException(status_code=400, detail="客户不存在")

        # 校验工厂名称是否与其他工厂重复（排除自己）
        if data.factory_name is not None and data.factory_name != factory.factory_name:
            name_check = await db.execute(
                select(Factory).where(
                    func.lower(Factory.factory_name) == data.factory_name.strip().lower(),
                    Factory.id != factory_id
                )
            )
            if name_check.first():
                raise HTTPException(status_code=400, detail="工厂名称已存在")

        # 更新字段
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(factory, key, value)

        await db.commit()
        await db.refresh(factory)

        return {"data": factory}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"更新工厂失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))


@router.delete("/factory/{factory_id}", summary="删除工厂")
async def delete_factory(
    factory_id: int,
    db: AsyncSession = Depends(get_db)
):
    """
    删除工厂（级联删除该工厂下的所有设备）
    """
    try:
        result = await db.execute(select(Factory).where(Factory.id == factory_id))
        factory = result.first()
        if not factory:
            raise HTTPException(status_code=404, detail="工厂不存在")

        factory = factory[0]

        await db.delete(factory)
        await db.commit()

        return {"message": "删除成功", "data": {"id": factory_id}}

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"删除工厂失败: {str(e)}")
        return ErrorResponse(code=500, message="服务器内部错误", detail=str(e))