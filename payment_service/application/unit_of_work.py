from types import TracebackType
from typing import Protocol, Self

from payment_service.application.repositories import OutboxRepository, PaymentRepository


class UnitOfWork(Protocol):
    payments: PaymentRepository
    outbox: OutboxRepository

    async def __aenter__(self) -> Self:
        """Begin a transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit on success; roll back on failure. Never suppress exceptions."""
        ...
