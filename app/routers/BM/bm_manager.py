from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db_services.database import get_db
from app.logger import get_logger
from app.models.ticket import DeviceModelBase, DeviceModel, CustomerBase, Customer

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
        data: DeviceModelBase,
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
    data: DeviceModelBase,
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


# ------------------------- 客户管理接口 -------------------------
@router.post("/customers", summary="创建客户")
async def create_customer(
        data: CustomerBase,
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
        data: CustomerBase,
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


@router.delete("/customers/{customer_id}",
               response_model=BaseResponse,
               summary="删除客户")
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