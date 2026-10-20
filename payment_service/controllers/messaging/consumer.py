import asyncio
import hashlib
import logging

from faststream import AckPolicy
from faststream.rabbit import Channel, RabbitBroker, RabbitMessage, RabbitQueue
from faststream.rabbit.message import RabbitMessage as Message
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from payment_service.application.errors import PaymentNotFoundError
from payment_service.application.processing import (
    PaymentGateway,
    ProcessingOutcome,
    RETRY_BASE_DELAY,
    WebhookSender,
    process_payment,
)
from payment_service.controllers.messaging.schemas import PaymentNew
from payment_service.infrastructure.messaging import DEAD_LETTER_QUEUE, PAYMENTS_QUEUE, publish_confirmed
from payment_service.infrastructure.unit_of_work import SQLAlchemyUnitOfWork


logger = logging.getLogger(__name__)
INFRASTRUCTURE_RETRY_DELAY = 1.0


async def wait_before_retry(delay: float) -> None:
    await asyncio.sleep(delay)


class PaymentConsumer:
    def __init__(
        self,
        broker: RabbitBroker,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: PaymentGateway,
        webhooks: WebhookSender,
        dead_letter_queue: RabbitQueue = DEAD_LETTER_QUEUE,
    ) -> None:
        self._broker = broker
        self._sessions = session_factory
        self._gateway = gateway
        self._webhooks = webhooks
        self._dead_letter_queue = dead_letter_queue

    async def handle(self, body: bytes, message: Message) -> None:
        try:
            try:
                event = PaymentNew.model_validate_json(body)
            except ValidationError:
                await self._publish_dead_letter(body, message, "invalid_payload", 0)
                await message.ack()
                return

            while True:
                try:
                    async with self._sessions() as session:
                        result = await process_payment(
                            event.payment_id, SQLAlchemyUnitOfWork(session),
                            self._gateway, self._webhooks,
                        )
                except PaymentNotFoundError:
                    await self._publish_dead_letter(body, message, "payment_not_found", 0)
                    await message.ack()
                    return
                if result.outcome is ProcessingOutcome.DONE:
                    await message.ack()
                    return
                if result.outcome is ProcessingOutcome.EXHAUSTED:
                    async with self._sessions() as session:
                        async with SQLAlchemyUnitOfWork(session) as work:
                            state = await work.payments.get_for_processing(event.payment_id)
                            if state is not None and not state.completed:
                                await self._publish_dead_letter(
                                    body, message, "attempts_exhausted", state.failures,
                                )
                                await work.payments.mark_dead_lettered(event.payment_id)
                    await message.ack()
                    return
                await wait_before_retry(RETRY_BASE_DELAY * 2 ** (result.failures - 1))
        except Exception:
            # Infrastructure failures must not acknowledge the original message.
            logger.exception("Consumer infrastructure failure; requeuing message")
            await wait_before_retry(INFRASTRUCTURE_RETRY_DELAY)
            await message.nack(requeue=True)

    async def _publish_dead_letter(
        self, body: bytes, message: Message, reason: str, failures: int,
    ) -> None:
        message_id = message.raw_message.message_id or hashlib.sha256(body).hexdigest()
        headers = dict(message.headers)
        headers.update({"x-error": reason, "x-processing-failures": failures})
        await publish_confirmed(
            self._broker, body, queue=self._dead_letter_queue.name,
            message_id=message_id, message_type="payments.dead",
            headers=headers, content_type=message.raw_message.content_type,
        )


def register_consumer(
    broker: RabbitBroker,
    session_factory: async_sessionmaker[AsyncSession],
    gateway: PaymentGateway,
    webhooks: WebhookSender,
    queue: RabbitQueue = PAYMENTS_QUEUE,
    dead_letter_queue: RabbitQueue = DEAD_LETTER_QUEUE,
) -> PaymentConsumer:
    consumer = PaymentConsumer(broker, session_factory, gateway, webhooks, dead_letter_queue)

    @broker.subscriber(
        queue, ack_policy=AckPolicy.MANUAL, channel=Channel(prefetch_count=1),
        decoder=lambda message: message.body,
    )
    async def handle(body: bytes, message: RabbitMessage) -> None:
        await consumer.handle(body, message)

    return consumer
