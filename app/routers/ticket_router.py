from fastapi import APIRouter, HTTPException, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.db_services.database import get_db
from app.services.ticket_service import (
    create_ticket_service, get_tickets_service, get_ticket_service,
    update_ticket_service, delete_ticket_service
)
from app.schemas.ticket_schema import TicketCreate, TicketResponse, TicketUpdate
from app.dependencies.auth import get_current_user
from app.models.user import User
from typing import List
from app.logger import get_logger

router = APIRouter()
logger = get_logger('ticket_router')


# 创建问题单
@router.post("/submit", response_model=TicketResponse)
async def create_ticket(
    ticket_data: TicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """创建问题单"""
    logger.info(f"收到创建问题单请求，当前用户: {current_user.id}")
    try:
        # 创建新的工单数据，包含用户ID
        ticket_dict = ticket_data.model_dump()
        ticket_dict["user_id"] = current_user.id
        
        # 调用服务层创建工单
        result = await create_ticket_service(db, ticket_dict)
        logger.info(f"成功创建问题单: {result.model_dump()}")
        return result
    except HTTPException as e:
        logger.error(f"创建问题单失败 - HTTP异常: {str(e)}")
        raise e
    except ValueError as e:
        logger.error(f"创建问题单失败 - 问题单数据验证失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"问题单数据验证失败: {str(e)}"
        )
    except Exception as e:
        logger.error(f"创建问题单失败 - 系统异常: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建问题单时发生错误: {str(e)}"
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
        tickets = await get_tickets_service(db)
        logger.info(f"成功获取问题单列表，共 {len(tickets)} 条记录")
        return tickets
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
        ticket = await get_ticket_service(db, ticket_id)
        logger.info(f"成功获取问题单信息: {ticket.model_dump()}")
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该问题单"
            )
        return {"ticket": ticket.model_dump()}
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
    ticket_data: TicketUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新问题单信息"""
    logger.info(f"收到更新问题单信息请求，问题单ID: {ticket_id}，当前用户: {current_user.id}")
    try:
        # 将当前用户ID添加到更新数据中
        update_dict = ticket_data.model_dump(exclude_unset=True)
        update_dict["user_id"] = current_user.id
        
        # 创建新的更新数据对象
        ticket_data_with_user = TicketUpdate(**update_dict)
        
        result = await update_ticket_service(db, ticket_id, ticket_data_with_user)
        logger.info(f"成功更新问题单信息: {result.model_dump()}")
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未找到该问题单"
            )
        return {"ticket": result.model_dump()}
    except HTTPException as e:
        logger.error(f"更新问题单信息失败 - HTTP异常: {str(e)}")
        raise e
    except Exception as e:
        logger.error(f"更新问题单信息失败 - 系统异常: {str(e)}", exc_info=True)
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
