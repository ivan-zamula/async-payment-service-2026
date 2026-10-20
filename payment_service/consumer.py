"""Run the single payment consumer: python -m payment_service.consumer."""

import asyncio
import logging
import signal

import httpx

from payment_service.controllers.messaging.consumer import register_consumer
from payment_service.infrastructure.database import connect_database, get_database_url
from payment_service.infrastructure.gateway import MockPaymentGateway
from payment_service.infrastructure.messaging import (
    DEAD_LETTER_QUEUE,
    PUBLISH_TIMEOUT,
    create_broker,
    get_rabbitmq_url,
)
from payment_service.infrastructure.webhooks import HTTPWebhookSender, WEBHOOK_TIMEOUT


logger = logging.getLogger(__name__)
CONNECTION_RETRY_DELAY = 1.0


async def run(stop: asyncio.Event) -> None:
    database_url = get_database_url()
    rabbitmq_url = get_rabbitmq_url()
    while not stop.is_set():
        try:
            async with connect_database(database_url) as session_factory:
                async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT, trust_env=False) as client:
                    async with create_broker(rabbitmq_url) as broker:
                        register_consumer(broker, session_factory, MockPaymentGateway(), HTTPWebhookSender(client))
                        async with asyncio.timeout(PUBLISH_TIMEOUT):
                            await broker.declare_queue(DEAD_LETTER_QUEUE)
                            await broker.start()
                        logger.info("Payment consumer started")
                        await stop.wait()
        except Exception:
            logger.exception("Consumer connection failed; retrying")
            try:
                await asyncio.wait_for(stop.wait(), timeout=CONNECTION_RETRY_DELAY)
            except TimeoutError:
                pass


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
