from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.ticket import Ticket
from app.schemas.ticket_schema import TicketCreate, TicketUpdate


async def create_ticket_service(session: AsyncSession, ticket_data: dict):
    """
    创建新的问题单
    
    Args:
        session: 数据库会话
        ticket_data: 问题单数据字典
        
    Returns:
        Ticket: 创建成功的问题单对象
    """
    try:
        # 确保ticket_data中包含user_id
        if 'user_id' not in ticket_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="创建工单失败: 缺少用户ID"
            )
            
        new_ticket = Ticket(**ticket_data)
        session.add(new_ticket)
        await session.commit()
        await session.refresh(new_ticket)
        return new_ticket
    except Exception as e:
        print(e," ----------------")
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建工单失败: {str(e)}"
        )


async def get_tickets_service(session: AsyncSession):
    """
    获取所有问题单
    
    Args:
        session: 数据库会话
        
    Returns:
        List[Ticket]: 问题单列表
    """
    try:
        result = await session.execute(select(Ticket))
        return result.scalars().all()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取工单列表失败: {str(e)}"
        )


async def get_ticket_service(session: AsyncSession, ticket_id: int):
    """
    根据ID获取问题单
    
    Args:
        session: 数据库会话
        ticket_id: 问题单ID
        
    Returns:
        Optional[Ticket]: 问题单对象，如果不存在则返回None
    """
    try:
        return await session.get(Ticket, ticket_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取工单详情失败: {str(e)}"
        )


async def update_ticket_service(session: AsyncSession, ticket_id: int, ticket_data: TicketUpdate):
    """
    更新问题单信息
    
    Args:
        session: 数据库会话
        ticket_id: 问题单ID
        ticket_data: 更新的问题单数据
        
    Returns:
        Optional[Ticket]: 更新后的问题单对象，如果不存在则返回None
    """
    try:
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            return None
        for field, value in ticket_data.model_dump(exclude_unset=True).items():
            setattr(ticket, field, value)
        await session.commit()
        await session.refresh(ticket)
        return ticket
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新工单失败: {str(e)}"
        )


async def delete_ticket_service(session: AsyncSession, ticket_id: int):
    """
    删除问题单
    
    Args:
        session: 数据库会话
        ticket_id: 问题单ID
        
    Returns:
        bool: 删除成功返回True，如果问题单不存在则返回None
    """
    try:
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            return None
        await session.delete(ticket)
        await session.commit()
        return True
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除工单失败: {str(e)}"
        )
