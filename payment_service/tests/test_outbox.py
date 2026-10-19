import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker
from pamqp.commands import Basic

from payment_service.application.events import OutboxEvent
from payment_service.infrastructure import messaging


@pytest.mark.parametrize("value", [
    None, "", " ", "http://localhost", "amqp:///", "amqp://user:secret@localhost:bad/",
    "amqp://localhost:0/",
])
def test_invalid_rabbitmq_url(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RABBITMQ_URL", raising=False)
    else:
        monkeypatch.setenv("RABBITMQ_URL", value)
    with pytest.raises(RuntimeError, match="RABBITMQ_URL") as error:
        messaging.get_rabbitmq_url()
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("confirmation", [None, False, Basic.Nack()])
def test_missing_positive_ack_is_a_failure(confirmation):
    broker = AsyncMock(spec=RabbitBroker)
    broker.publish.return_value = confirmation
    event = OutboxEvent(id=uuid4(), event_type="payments.new", payload={"payment_id": str(uuid4())})

    async def run():
        with pytest.raises(RuntimeError, match="acknowledge"):
            await messaging.RabbitMQEventPublisher(broker).publish(event)

    asyncio.run(run())


def test_entire_publish_operation_has_a_timeout(monkeypatch):
    monkeypatch.setattr(messaging, "PUBLISH_TIMEOUT", 0.01)
    broker = AsyncMock(spec=RabbitBroker)

    async def never_connected(*args, **kwargs):
        await asyncio.Event().wait()

    broker.publish.side_effect = never_connected
    event = OutboxEvent(id=uuid4(), event_type="payments.new", payload={})

    async def run():
        with pytest.raises(TimeoutError):
            await messaging.RabbitMQEventPublisher(broker).publish(event)

    asyncio.run(run())
