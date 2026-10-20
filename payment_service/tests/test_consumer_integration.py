import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest
from faststream.rabbit import RabbitBroker, RabbitQueue
from faststream.rabbit.message import RabbitMessage
from pamqp.commands import Basic
from sqlalchemy import select

from payment_service.application.processing import PaymentGateway, WebhookSender
from payment_service.controllers.messaging import consumer as consumer_module
from payment_service.controllers.messaging.consumer import PaymentConsumer, register_consumer
from payment_service.domain.entities import PaymentStatus
from payment_service.infrastructure.messaging import create_broker, publish_confirmed
from payment_service.infrastructure.models import PaymentModel
from payment_service.tests.helpers import isolated_database, seed_payment


@pytest.fixture
def retry_wait(monkeypatch):
    wait = AsyncMock()
    monkeypatch.setattr(consumer_module, "wait_before_retry", wait)
    return wait


def message():
    value = AsyncMock(spec=RabbitMessage)
    value.raw_message = SimpleNamespace(message_id=str(uuid4()), content_type="application/json")
    value.headers = {}
    return value


def gateway():
    value = AsyncMock(spec=PaymentGateway)
    value.process.return_value = True
    return value


def broker():
    value = AsyncMock(spec=RabbitBroker)
    value.publish.return_value = Basic.Ack()
    return value


async def state(sessions, payment_id):
    async with sessions() as session:
        return (await session.execute(select(
            PaymentModel.status, PaymentModel.processing_failures, PaymentModel.webhook_sent_at,
            PaymentModel.dead_lettered_at,
        ).where(PaymentModel.id == payment_id))).one()


def test_webhook_retry_backoff_and_ack(database_url, retry_wait):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            provider, notifications, rabbit = gateway(), AsyncMock(spec=WebhookSender), broker()
            notifications.send.side_effect = [TimeoutError(), TimeoutError(), None]
            consumer = PaymentConsumer(rabbit, sessions, provider, notifications)
            incoming = message()
            await consumer.handle(json.dumps({"payment_id": str(payment.id)}).encode(), incoming)
            incoming.ack.assert_awaited_once()
            incoming.nack.assert_not_awaited()
            provider.process.assert_awaited_once()
            assert notifications.send.await_count == 3
            assert retry_wait.await_args_list == [call(2.0), call(4.0)]
            rabbit.publish.assert_not_awaited()
            assert (await state(sessions, payment.id)).webhook_sent_at is not None

    asyncio.run(run())


def test_third_failure_goes_to_dlq_once(database_url, retry_wait):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            provider, notifications, rabbit = gateway(), AsyncMock(spec=WebhookSender), broker()
            notifications.send.side_effect = TimeoutError()
            consumer = PaymentConsumer(rabbit, sessions, provider, notifications)
            incoming = message()
            body = json.dumps({"payment_id": str(payment.id)}).encode()
            await consumer.handle(body, incoming)
            stored = await state(sessions, payment.id)
            assert stored.status is PaymentStatus.SUCCEEDED and stored.processing_failures == 3
            assert stored.webhook_sent_at is None and stored.dead_lettered_at is not None
            incoming.ack.assert_awaited_once()
            incoming.nack.assert_not_awaited()
            rabbit.publish.assert_awaited_once()
            arguments = rabbit.publish.call_args
            assert arguments.args[0] == body
            assert arguments.kwargs["queue"] == "payments.dlq"
            assert arguments.kwargs["message_id"] == incoming.raw_message.message_id
            assert arguments.kwargs["headers"]["x-processing-failures"] == 3
            await consumer.handle(body, message())
            provider.process.assert_awaited_once()
            assert notifications.send.await_count == 3
            rabbit.publish.assert_awaited_once()

    asyncio.run(run())


def test_dlq_failure_nacks_original_and_retry_does_not_repeat_work(database_url, retry_wait):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            provider, notifications, rabbit = gateway(), AsyncMock(spec=WebhookSender), broker()
            notifications.send.side_effect = TimeoutError()
            rabbit.publish.side_effect = ConnectionError("DLQ unavailable")
            consumer = PaymentConsumer(rabbit, sessions, provider, notifications)
            incoming = message()
            body = json.dumps({"payment_id": str(payment.id)}).encode()
            await consumer.handle(body, incoming)
            incoming.ack.assert_not_awaited()
            incoming.nack.assert_awaited_once_with(requeue=True)
            assert (await state(sessions, payment.id)).dead_lettered_at is None
            rabbit.publish.side_effect = None
            retry = message()
            await consumer.handle(body, retry)
            retry.ack.assert_awaited_once()
            assert (await state(sessions, payment.id)).dead_lettered_at is not None
            provider.process.assert_awaited_once()
            assert notifications.send.await_count == 3

    asyncio.run(run())


def test_ack_failure_does_not_repeat_successful_webhook(database_url, retry_wait):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            provider, notifications = gateway(), AsyncMock(spec=WebhookSender)
            consumer = PaymentConsumer(broker(), sessions, provider, notifications)
            incoming = message()
            incoming.ack.side_effect = ConnectionError("Ack lost")
            body = json.dumps({"payment_id": str(payment.id)}).encode()
            await consumer.handle(body, incoming)
            incoming.nack.assert_awaited_once_with(requeue=True)
            await consumer.handle(body, message())
            provider.process.assert_awaited_once()
            notifications.send.assert_awaited_once()

    asyncio.run(run())


def test_cancellation_leaves_message_unacknowledged_and_payment_pending(database_url, retry_wait):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            provider, notifications = gateway(), AsyncMock(spec=WebhookSender)
            provider.process.side_effect = asyncio.CancelledError()
            consumer = PaymentConsumer(broker(), sessions, provider, notifications)
            incoming = message()
            with pytest.raises(asyncio.CancelledError):
                await consumer.handle(json.dumps({"payment_id": str(payment.id)}).encode(), incoming)
            incoming.ack.assert_not_awaited()
            incoming.nack.assert_not_awaited()
            notifications.send.assert_not_awaited()
            stored = await state(sessions, payment.id)
            assert stored.status is PaymentStatus.PENDING and stored.processing_failures == 0

    asyncio.run(run())


def test_missing_payment_goes_to_dlq(database_url, retry_wait):
    async def run():
        async with isolated_database(database_url) as sessions:
            rabbit, incoming, provider = broker(), message(), gateway()
            await PaymentConsumer(rabbit, sessions, provider, AsyncMock(spec=WebhookSender)).handle(
                json.dumps({"payment_id": str(uuid4())}).encode(), incoming,
            )
            incoming.ack.assert_awaited_once()
            provider.process.assert_not_awaited()
            assert rabbit.publish.call_args.kwargs["headers"]["x-error"] == "payment_not_found"

    asyncio.run(run())


@pytest.mark.parametrize("body", [b"not-json", b"{}", b'{"payment_id":"bad"}', b'\xff'])
def test_malformed_message_goes_to_dlq(body, retry_wait):
    async def run():
        rabbit = broker()
        incoming = message()
        await PaymentConsumer(rabbit, None, gateway(), AsyncMock(spec=WebhookSender)).handle(body, incoming)
        incoming.ack.assert_awaited_once()
        assert rabbit.publish.call_args.kwargs["headers"]["x-error"] == "invalid_payload"

    asyncio.run(run())


@pytest.mark.parametrize("fails", [False, True])
def test_real_rabbitmq_consumer_and_dlq(database_url, retry_wait, fails):
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("Set TEST_RABBITMQ_URL to an isolated test broker")

    async def run():
        queue = RabbitQueue("test.consumer." + uuid4().hex, durable=True)
        dead = RabbitQueue("test.dlq." + uuid4().hex, durable=True)
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            provider, notifications = gateway(), AsyncMock(spec=WebhookSender)
            if fails:
                notifications.send.side_effect = TimeoutError("Webhook unavailable")
            async with create_broker(url) as rabbit:
                declared = await rabbit.declare_queue(queue)
                dlq = await rabbit.declare_queue(dead)
                register_consumer(rabbit, sessions, provider, notifications, queue, dead)
                try:
                    await rabbit.start()
                    event_id = str(uuid4())
                    await publish_confirmed(rabbit, {"payment_id": str(payment.id)}, queue=queue.name,
                                            message_id=event_id, message_type="payments.new")
                    async with asyncio.timeout(5):
                        while True:
                            stored = await state(sessions, payment.id)
                            delivered = stored.dead_lettered_at if fails else stored.webhook_sent_at
                            if delivered:
                                break
                            await asyncio.sleep(0.01)
                    if fails:
                        failed = await dlq.get(timeout=3, fail=True)
                        assert failed.message_id == event_id
                        assert failed.headers["x-processing-failures"] == 3
                        await failed.ack()
                    else:
                        # Replay the event after delivery: no extra gateway or webhook call.
                        await publish_confirmed(rabbit, {"payment_id": str(payment.id)}, queue=queue.name,
                                                message_id=event_id, message_type="payments.new")
                        await asyncio.sleep(0.05)
                    provider.process.assert_awaited_once()
                    assert notifications.send.await_count == (3 if fails else 1)
                finally:
                    await declared.delete(if_unused=False, if_empty=False)
                    await dlq.delete(if_unused=False, if_empty=False)

    asyncio.run(run())


def test_real_malformed_message_reaches_dlq(database_url, retry_wait):
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("Set TEST_RABBITMQ_URL to an isolated test broker")

    async def run():
        queue = RabbitQueue("test.consumer." + uuid4().hex, durable=True)
        dead = RabbitQueue("test.dlq." + uuid4().hex, durable=True)
        async with isolated_database(database_url) as sessions:
            async with create_broker(url) as rabbit:
                declared = await rabbit.declare_queue(queue)
                dlq = await rabbit.declare_queue(dead)
                provider = gateway()
                register_consumer(rabbit, sessions, provider, AsyncMock(spec=WebhookSender), queue, dead)
                try:
                    await rabbit.start()
                    event_id = str(uuid4())
                    await publish_confirmed(rabbit, b'\xff', queue=queue.name, message_id=event_id,
                                            message_type="payments.new", content_type="application/json")
                    async with asyncio.timeout(5):
                        while True:
                            failed = await dlq.get(fail=False)
                            if failed is not None:
                                break
                            await asyncio.sleep(0.01)
                    assert failed.body == b'\xff'
                    assert failed.message_id == event_id
                    assert failed.headers["x-error"] == "invalid_payload"
                    await failed.ack()
                    provider.process.assert_not_awaited()
                finally:
                    await declared.delete(if_unused=False, if_empty=False)
                    await dlq.delete(if_unused=False, if_empty=False)

    asyncio.run(run())
