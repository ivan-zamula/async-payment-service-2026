from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.application.repositories import PaymentRepository
from payment_service.application.unit_of_work import UnitOfWork
from payment_service.infrastructure.repositories import SQLAlchemyPaymentRepository
from payment_service.infrastructure.unit_of_work import SQLAlchemyUnitOfWork


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # UnitOfWork commits; closing the session rolls back unfinished work.
    async with request.app.state.session_factory() as session:
        yield session


async def get_payment_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentRepository:
    return SQLAlchemyPaymentRepository(session)


async def get_unit_of_work(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UnitOfWork:
    return SQLAlchemyUnitOfWork(session)
