from typing import Protocol
from uuid import UUID

from payment_service.application.dto import PaymentProcessingState
from payment_service.application.events import OutboxEvent
from payment_service.domain.entities import Payment


class PaymentRepository(Protocol):
    """The caller owns the transaction."""

    async def add(self, payment: Payment) -> None:
        """Flush the insert without committing."""
        ...

    async def add_if_absent(self, payment: Payment) -> bool:
        """Insert atomically; return False if the idempotency key already exists."""
        ...

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        ...

    async def get_for_processing(self, payment_id: UUID) -> PaymentProcessingState | None:
        """Lock the row until the transaction ends."""
        ...

    async def save_result(self, payment: Payment) -> None:
        """Save final status and processing time without changing request data."""
        ...

    async def record_processing_failure(self, payment_id: UUID) -> None:
        ...

    async def mark_webhook_sent(self, payment_id: UUID) -> None:
        ...

    async def mark_dead_lettered(self, payment_id: UUID) -> None:
        ...


class OutboxRepository(Protocol):
    async def add_payment_created(self, payment: Payment) -> None:
        """Save payments.new in the same transaction as the payment."""
        ...

    async def get_next_unpublished(self) -> OutboxEvent | None:
        """Lock one pending event until transaction end, skipping locked events."""
        ...

    async def record_attempt(self, event_id: UUID) -> None:
        ...

    async def mark_published(self, event_id: UUID) -> None:
        """Call after the broker confirms publication."""
        ...
