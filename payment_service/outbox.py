"""Run the outbox publisher: python -m payment_service.outbox."""

import asyncio
import logging
import signal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.application.publishing import (
    EventPublisher,
    PublicationResult,
    publish_next_event,
)
from payment_service.infrastructure.database import connect_database, get_database_url
from payment_service.infrastructure.messaging import (
    PAYMENTS_QUEUE,
    PUBLISH_TIMEOUT,
    RabbitMQEventPublisher,
    create_broker,
    get_rabbitmq_url,
)
from payment_service.infrastructure.unit_of_work import SQLAlchemyUnitOfWork


logger = logging.getLogger(__name__)
POLL_INTERVAL = 1.0


async def wait_for_retry(stop: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
    except TimeoutError:
        pass


async def publish_pending(
    session_factory: async_sessionmaker[AsyncSession],
    publisher: EventPublisher,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        async with session_factory() as session:
            result = await publish_next_event(SQLAlchemyUnitOfWork(session), publisher)
        if result is not PublicationResult.SENT:
            await wait_for_retry(stop)


async def run(stop: asyncio.Event) -> None:
    database_url = get_database_url()
    rabbitmq_url = get_rabbitmq_url()
    while not stop.is_set():
        try:
            async with connect_database(database_url) as session_factory:
                async with create_broker(rabbitmq_url) as broker:
                    async with asyncio.timeout(PUBLISH_TIMEOUT):
                        await broker.declare_queue(PAYMENTS_QUEUE)
                    logger.info("Outbox publisher started")
                    await publish_pending(session_factory, RabbitMQEventPublisher(broker), stop)
        except Exception:
            logger.exception("Outbox publisher connection failed; retrying")
            await wait_for_retry(stop)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await run(stop)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
