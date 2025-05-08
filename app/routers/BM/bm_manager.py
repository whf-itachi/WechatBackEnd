from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import func
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db_services.database import get_db
from app.logger import get_logger
from app.models.ticket import DeviceModelBase, DeviceModel, CustomerBase, Customer
from app.schemas.manage_schema import DeviceModelResponse

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
async def create_device_model(data: DeviceModelBase, db: AsyncSession = Depends(get_db)):
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


@router.put("/device_models/{model_id}", response_model=DeviceModelResponse, summary="更新设备型号")
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
@router.post("/customers",
             response_model=BaseResponse,
             status_code=status.HTTP_201_CREATED,
             summary="创建客户",
             responses={
                 400: {"model": ErrorResponse},
                 500: {"model": ErrorResponse}
             })
async def create_customer(
        data: CustomerBase,
        db: AsyncSession = Depends(get_db)
):
    """创建新客户（自动生成创建时间）"""
    try:
        # 唯一性检查
        exist_stmt = select(Customer).where(
            Customer.customer == data.customer
        )
        if (await db.execute(exist_stmt)).scalar():
            logger.warning(f"客户名称重复: {data.customer}")
            raise HTTPException(400, detail="客户名称已存在")

        # 模型转换
        new_customer = Customer(**data.model_dump())
        db.add(new_customer)
        await db.commit()
        await db.refresh(new_customer)

        logger.info(f"客户创建成功 | ID:{new_customer.id}")
        return BaseResponse(
            data=new_customer.model_dump(),
            message="创建成功"
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        await db.rollback()
        logger.error(
            f"客户创建失败 | 名称:{data.customer} | 错误:{str(e)}",
            exc_info=True
        )
        return ErrorResponse(
            code=500,
            message="服务器内部错误",
            detail="系统繁忙，请稍后重试"
        )


@router.get("/customers",
            response_model=BaseResponse,
            summary="分页获取客户列表",
            responses={
                500: {"model": ErrorResponse}
            })
async def list_customers(
        page: int = Query(1, ge=1),
        size: int = Query(10, ge=1),
        db: AsyncSession = Depends(get_db)
):
    """获取客户列表（分页）"""
    try:
        stmt = select(Customer)
        count_stmt = select(func.count()).select_from(stmt.subquery())

        total_result = await db.execute(count_stmt)
        total = total_result.scalar()

        result = await db.execute(
            stmt.order_by(Customer.id.desc()).offset((page - 1) * size).limit(size)
        )
        customers = result.scalars().all()

        return BaseResponse(
            data={
                "items": [c.dict() for c in customers],
                "total": total
            },
            message="获取成功"
        )
    except Exception as e:
        logger.error(f"客户列表获取失败: {str(e)}", exc_info=True)
        return ErrorResponse(
            code=500,
            message="服务器内部错误",
            detail="系统繁忙，请稍后重试"
        )


@router.patch("/customers/{customer_id}",
              response_model=BaseResponse,
              summary="更新客户信息",
              responses={
                  404: {"model": ErrorResponse},
                  400: {"model": ErrorResponse},
                  500: {"model": ErrorResponse}
              })
async def update_customer(
        customer_id: int,
        data: CustomerBase,
        db: AsyncSession = Depends(get_db)
):
    """更新客户信息（带版本控制）"""
    try:
        # 获取客户实例
        customer = await db.get(Customer, customer_id)
        if not customer:
            logger.warning(f"无效客户ID: {customer_id}")
            raise HTTPException(404, detail="客户不存在")

        # 名称变更校验
        if data.customer != customer.customer:
            exist_stmt = select(Customer.id).where(
                Customer.customer == data.customer,
                Customer.id != customer_id
            )
            if (await db.execute(exist_stmt)).scalar():
                logger.warning(f"名称冲突 | 原:{customer.customer} 新:{data.customer}")
                raise HTTPException(400, detail="客户名称已存在")

        # 执行更新
        for field, value in data.model_dump().items():
            setattr(customer, field, value)

        customer.updated_at = datetime.now()
        await db.commit()
        await db.refresh(customer)

        logger.info(f"客户更新成功 | ID:{customer_id}")
        return BaseResponse(
            data=customer.model_dump(),
            message="更新成功"
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        await db.rollback()
        logger.error(
            f"客户更新失败 | ID:{customer_id} | 错误:{str(e)}",
            exc_info=True
        )
        return ErrorResponse(
            code=500,
            message="服务器内部错误",
            detail="系统繁忙，请稍后重试"
        )


@router.delete("/customers/{customer_id}",
               response_model=BaseResponse,
               summary="删除客户",
               responses={
                   404: {"model": ErrorResponse},
                   500: {"model": ErrorResponse}
               })
async def delete_customer(
        customer_id: int,
        db: AsyncSession = Depends(get_db)
):
    """标记删除客户（保留历史数据）"""
    try:
        # 获取有效客户
        stmt = select(Customer).where(
            Customer.id == customer_id
        )
        customer = (await db.execute(stmt)).scalar()
        if not customer:
            logger.warning(f"删除无效客户ID: {customer_id}")
            raise HTTPException(404, detail="客户不存在")

        # 执行软删除
        customer.is_deleted = True
        customer.deleted_at = datetime.now()
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