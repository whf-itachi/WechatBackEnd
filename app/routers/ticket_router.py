from fastapi import APIRouter, HTTPException
from app.db_services.database import AsyncSessionDep
from app.services.ticket_service import (
    create_ticket_service, get_tickets_service, get_ticket_service,
    update_ticket_service, delete_ticket_service
)
from app.schemas.ticket_schema import TicketCreate, TicketResponse, TicketUpdate
from typing import List

router = APIRouter(prefix="/tickets", tags=["问题单管理"])


# 创建问题单
@router.post("/", response_model=TicketResponse)
async def create_ticket(ticket_data: TicketCreate, session: AsyncSessionDep):
    try:
        print("...............///", ticket_data)
        result = await create_ticket_service(session, ticket_data)
        print(f"成功创建问题单，问题单 ID: {result.id}")
        return result
    except Exception as e:
        print(f"创建问题单时出错: {e}")
        raise HTTPException(status_code=500, detail="创建问题单时发生错误")


# 查询所有问题单
@router.get("/", response_model=List[TicketResponse])
async def get_tickets(session: AsyncSessionDep):
    try:
        tickets = await get_tickets_service(session)
        return tickets
    except Exception as e:
        print(f"查询所有问题单时出错: {e}")
        raise HTTPException(status_code=500, detail="查询所有问题单时发生错误")


# 根据问题单 id 查询问题单信息
@router.get("/{ticket_id}", response_model=TicketResponse)
async def get_ticket(ticket_id: int, session: AsyncSessionDep):
    try:
        ticket = await get_ticket_service(session, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="未找到该问题单")
        return ticket
    except HTTPException:
        raise
    except Exception as e:
        print(f"查询问题单信息时出错，问题单 ID: {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail="查询问题单信息时发生错误")


# 根据问题单 id 修改问题单信息
@router.put("/{ticket_id}", response_model=TicketResponse)
async def update_ticket(ticket_id: int, ticket_data: TicketUpdate, session: AsyncSessionDep):
    try:
        result = await update_ticket_service(session, ticket_id, ticket_data)
        if not result:
            raise HTTPException(status_code=404, detail="未找到该问题单")
        print(f"成功更新问题单，问题单 ID: {ticket_id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"更新问题单信息时出错，问题单 ID: {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail="更新问题单信息时发生错误")


# 根据问题单 id 删除问题单
@router.delete("/{ticket_id}")
async def delete_ticket(ticket_id: int, session: AsyncSessionDep):
    try:
        result = await delete_ticket_service(session, ticket_id)
        if not result:
            raise HTTPException(status_code=404, detail="未找到该问题单")
        print(f"成功删除问题单，问题单 ID: {ticket_id}")
        return {"message": "问题单删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"删除问题单时出错，问题单 ID: {ticket_id}: {e}")
        raise HTTPException(status_code=500, detail="删除问题单时发生错误")
