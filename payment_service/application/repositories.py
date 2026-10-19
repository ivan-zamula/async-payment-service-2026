"""Repository interfaces required by application scenarios."""

from typing import Protocol
from uuid import UUID

from payment_service.application.events import OutboxEvent
from payment_service.domain.entities import Payment


class PaymentRepository(Protocol):
    """Work with payments inside a transaction managed by the caller."""

    async def add(self, payment: Payment) -> None:
        """Add a new payment to the current transaction without committing it."""
        ...

    async def add_if_absent(self, payment: Payment) -> bool:
        """Insert atomically; return False if the idempotency key already exists."""
        ...

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        """Return a payment by its ID, or None if it does not exist."""
        ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        """Return a payment by its idempotency key, or None if it does not exist."""
        ...


class OutboxRepository(Protocol):
    async def add_payment_created(self, payment: Payment) -> None:
        """Stage a payments.new event in the current transaction without committing."""
        ...

    async def get_next_unpublished(self) -> OutboxEvent | None:
        """Lock one pending event until transaction end, skipping locked events."""
        ...

    async def record_attempt(self, event_id: UUID) -> None:
        """Increment publication attempts in the current transaction."""
        ...

    async def mark_published(self, event_id: UUID) -> None:
        """Set publication time in the current transaction after acknowledgement."""
        ...
