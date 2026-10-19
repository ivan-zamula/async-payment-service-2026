"""SQLAlchemy transaction boundary for payment creation."""

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.application.unit_of_work import UnitOfWork
from payment_service.infrastructure.repositories import (
    SQLAlchemyOutboxRepository,
    SQLAlchemyPaymentRepository,
)


class SQLAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.payments = SQLAlchemyPaymentRepository(session)
        self.outbox = SQLAlchemyOutboxRepository(session)

    async def __aenter__(self) -> Self:
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self._session.rollback()
            return
        try:
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise
