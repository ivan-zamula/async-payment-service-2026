"""Confirmed, persistent RabbitMQ publication through FastStream."""

import asyncio
import os
from urllib.parse import urlsplit

from faststream.rabbit import Channel, RabbitBroker, RabbitQueue
from pamqp.commands import Basic

from payment_service.application.events import OutboxEvent
from payment_service.application.publishing import EventPublisher


PAYMENTS_QUEUE = RabbitQueue("payments.new", durable=True)
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
        url, timeout=PUBLISH_TIMEOUT,
        default_channel=Channel(publisher_confirms=True, on_return_raises=True),
    )


class RabbitMQEventPublisher(EventPublisher):
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publish(self, event: OutboxEvent) -> None:
        # Bound the entire operation, including waiting for a disconnected channel.
        async with asyncio.timeout(PUBLISH_TIMEOUT):
            confirmation = await self._broker.publish(
                event.payload, queue=event.event_type,
                persist=True, mandatory=True, timeout=PUBLISH_TIMEOUT,
                message_id=str(event.id), message_type=event.event_type,
            )
        if not isinstance(confirmation, Basic.Ack):
            raise RuntimeError("RabbitMQ did not acknowledge the event")
