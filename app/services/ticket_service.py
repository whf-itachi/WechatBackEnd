from sqlalchemy import select

from app.db_services.database import AsyncSessionDep
from app.models.ticket import Ticket
from app.schemas.ticket_schema import TicketCreate, TicketUpdate


async def create_ticket_service(session: AsyncSessionDep, ticket_data: TicketCreate):
    new_ticket = Ticket(**ticket_data.model_dump())
    session.add(new_ticket)
    await session.commit()
    await session.refresh(new_ticket)
    return new_ticket


async def get_tickets_service(session: AsyncSessionDep):
    result = await session.execute(select(Ticket))

    return result.scalars().all()


async def get_ticket_service(session: AsyncSessionDep, ticket_id: int):
    return session.get(Ticket, ticket_id)


async def update_ticket_service(session: AsyncSessionDep, ticket_id: int, ticket_data: TicketUpdate):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        return None
    for field, value in ticket_data.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    session.commit()
    session.refresh(ticket)
    return ticket


async def delete_ticket_service(session: AsyncSessionDep, ticket_id: int):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        return None
    session.delete(ticket)
    session.commit()
    return True
