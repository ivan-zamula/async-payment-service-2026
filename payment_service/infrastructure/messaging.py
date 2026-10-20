"""Confirmed, persistent RabbitMQ publication through FastStream."""

import asyncio
import os
from typing import Any
from urllib.parse import urlsplit

from faststream.rabbit import Channel, RabbitBroker, RabbitQueue
from pamqp.commands import Basic

from payment_service.application.events import OutboxEvent
from payment_service.application.publishing import EventPublisher


PAYMENTS_QUEUE = RabbitQueue("payments.new", durable=True)
DEAD_LETTER_QUEUE = RabbitQueue("payments.dlq", durable=True)
PUBLISH_TIMEOUT = 5.0


def get_rabbitmq_url() -> str:
    value = os.environ.get("RABBITMQ_URL", "")
    try:
        url = urlsplit(value)
        valid = url.scheme in {"amqp", "amqps"} and url.hostname and url.port != 0
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("Set RABBITMQ_URL to an amqp:// or amqps:// URL with a host")
    return value


def create_broker(url: str) -> RabbitBroker:
    return RabbitBroker(
        url, timeout=PUBLISH_TIMEOUT, graceful_timeout=15,
        default_channel=Channel(publisher_confirms=True, on_return_raises=True),
    )


class RabbitMQEventPublisher(EventPublisher):
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publish(self, event: OutboxEvent) -> None:
        await publish_confirmed(
            self._broker, event.payload, queue=event.event_type,
            message_id=str(event.id), message_type=event.event_type,
        )


async def publish_confirmed(
    broker: RabbitBroker,
    message: dict[str, Any] | bytes,
    *,
    queue: str,
    message_id: str,
    message_type: str,
    headers: dict[str, Any] | None = None,
    content_type: str | None = None,
) -> None:
    # Bound the entire operation, including waiting for a disconnected channel.
    async with asyncio.timeout(PUBLISH_TIMEOUT):
        confirmation = await broker.publish(
            message, queue=queue, persist=True, mandatory=True, timeout=PUBLISH_TIMEOUT,
            message_id=message_id, message_type=message_type,
            headers=headers, content_type=content_type,
        )
    if not isinstance(confirmation, Basic.Ack):
        raise RuntimeError("RabbitMQ did not acknowledge the event")
