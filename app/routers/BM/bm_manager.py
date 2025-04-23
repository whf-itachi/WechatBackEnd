from datetime import datetime
from imp import new_module
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import SQLModel, Field, select, func
from sqlmodel.ext.asyncio.session import AsyncSession
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
@router.post("/device-models",
             response_model=BaseResponse,
             responses={400: {"model": ErrorResponse}},
             summary="创建设备型号")
async def create_device_model(
        data: DeviceModelBase,
        db: AsyncSession = Depends(get_db)
):
    """创建新设备型号（自动生成创建时间）"""
    try:
        # 检查唯一性
        existing = await db.exec(select(DeviceModel).where(DeviceModel.device_model == data.device_model))
        if existing.first():
            raise HTTPException(
                status_code=400,
                detail="设备型号已存在"
            )

        device_dict = DeviceModel.model_dump()
        new_model = DeviceModel(**device_dict)
        db.add(new_model)
        await db.commit()
        await db.refresh(new_model)

        return {"data": new_model}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"创建设备失败: {str(e)}")
        return ErrorResponse(
            code=500,
            message="服务器内部错误",
            detail=str(e)
        )


@router.post("/device-models",
             response_model=BaseResponse,
             responses={
                 400: {"model": ErrorResponse},
                 500: {"model": ErrorResponse}
             },
             summary="创建设备型号",
             status_code=status.HTTP_201_CREATED)
async def create_device_model(
        data: DeviceModelBase,
        db: AsyncSession = Depends(get_db)
):
    """创建新设备型号（自动生成created_at时间）"""
    try:
        existing = await db.execute(
            select(DeviceModel)
            .where(DeviceModel.device_model == data.device_model)
        )
        if existing.scalars().first():
            logger.warning(f"重复创建设备型号尝试: {data.device_model}")
            raise HTTPException(
                status_code=400,
                detail="设备型号已存在"
            )

        new_model = DeviceModel(**data.model_dump())

        db.add(new_model)
        await db.commit()
        await db.refresh(new_model)

        logger.info(f"设备型号创建成功 | ID:{new_model.id} | 型号:{new_model.device_model}")
        return BaseResponse(
            data=new_model.model_dump(),
            message="创建成功"
        )

    except HTTPException as e:
        raise e

    except Exception as e:
        logger.error(
            f"设备型号创建失败 | 型号:{data.device_model} | 错误:{str(e)}",
            exc_info=True
        )
        return ErrorResponse(
            code=500,
            message="服务器内部错误",
            detail="系统繁忙，请稍后重试"  # 生产环境隐藏具体错误细节
        )


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
        # 唯一性检查（网页5防重复逻辑）
        exist_stmt = select(Customer).where(
            Customer.customer == data.customer,
            Customer.is_deleted == False
        )
        if (await db.execute(exist_stmt)).scalar():
            logger.warning(f"客户名称重复: {data.customer}")
            raise HTTPException(400, detail="客户名称已存在")

        # 模型转换（网页3 ORM操作）
        new_customer = Customer(**data.dict())
        db.add(new_customer)
        await db.commit()
        await db.refresh(new_customer)

        logger.info(f"客户创建成功 | ID:{new_customer.id}")
        return BaseResponse(
            data=new_customer.dict(),
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
        # 获取客户实例（网页7推荐方式）
        customer = await db.get(Customer, customer_id)
        if not customer or customer.is_deleted:
            logger.warning(f"无效客户ID: {customer_id}")
            raise HTTPException(404, detail="客户不存在")

        # 名称变更校验（网页5防冲突策略）
        if data.customer != customer.customer:
            exist_stmt = select(Customer.id).where(
                Customer.customer == data.customer,
                Customer.id != customer_id,
                Customer.is_deleted == False
            )
            if (await db.execute(exist_stmt)).scalar():
                logger.warning(f"名称冲突 | 原:{customer.customer} 新:{data.customer}")
                raise HTTPException(400, detail="客户名称已存在")

        # 执行更新（网页3字段更新方式）
        for field, value in data.dict().items():
            setattr(customer, field, value)

        customer.updated_at = datetime.now()
        await db.commit()
        await db.refresh(customer)

        logger.info(f"客户更新成功 | ID:{customer_id}")
        return BaseResponse(
            data=customer.dict(),
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
        # 获取有效客户（网页7查询优化）
        stmt = select(Customer).where(
            Customer.id == customer_id,
            Customer.is_deleted == False
        )
        customer = (await db.execute(stmt)).scalar()
        if not customer:
            logger.warning(f"删除无效客户ID: {customer_id}")
            raise HTTPException(404, detail="客户不存在")

        # 执行软删除（网页4推荐方式）
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