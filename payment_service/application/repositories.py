"""Repository interfaces required by application scenarios."""

from typing import Protocol
from uuid import UUID

from payment_service.domain.entities import Payment


class PaymentRepository(Protocol):
    """Work with payments inside a transaction managed by the caller."""

    async def add(self, payment: Payment) -> None:
        """Add a new payment to the current transaction without committing it."""
        ...

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        """Return a payment by its ID, or None if it does not exist."""
        ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        """Return a payment by its idempotency key, or None if it does not exist."""
        ...
