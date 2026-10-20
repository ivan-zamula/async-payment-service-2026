import logging
from enum import StrEnum
from typing import Protocol

from payment_service.application.events import OutboxEvent
from payment_service.application.unit_of_work import UnitOfWork


logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    async def publish(self, event: OutboxEvent) -> None:
        """Return only after broker acknowledgement; raise on rejection or timeout."""
        ...


class PublicationResult(StrEnum):
    EMPTY = "empty"
    SENT = "sent"
    FAILED = "failed"


async def publish_next_event(
    unit_of_work: UnitOfWork, publisher: EventPublisher,
) -> PublicationResult:
    async with unit_of_work:
        event = await unit_of_work.outbox.get_next_unpublished()
        if event is None:
            return PublicationResult.EMPTY
        await unit_of_work.outbox.record_attempt(event.id)
        try:
            await publisher.publish(event)
        except Exception:
            # Commit the attempt counter, leaving published_at empty for a retry.
            logger.exception("Outbox publication failed: event_id=%s", event.id)
            return PublicationResult.FAILED
        await unit_of_work.outbox.mark_published(event.id)
        logger.info("Outbox event acknowledged: event_id=%s", event.id)
    return PublicationResult.SENT
