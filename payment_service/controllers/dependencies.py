"""Request-scoped dependencies for HTTP handlers."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.application.repositories import PaymentRepository
from payment_service.infrastructure.repositories import SQLAlchemyPaymentRepository


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # Closing a session also rolls back any uncommitted transaction.
    # The application use case will explicitly choose when to commit.
    async with request.app.state.session_factory() as session:
        yield session


async def get_payment_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaymentRepository:
    return SQLAlchemyPaymentRepository(session)
