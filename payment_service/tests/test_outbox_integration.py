"""Outbox transaction checks on PostgreSQL and real RabbitMQ routing checks."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from aio_pika import DeliveryMode
from faststream.rabbit import RabbitQueue
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from payment_service.application.handlers import create_payment
from payment_service.application.publishing import EventPublisher, PublicationResult, publish_next_event
from payment_service.domain.entities import Currency, Payment
from payment_service.infrastructure.messaging import RabbitMQEventPublisher, create_broker
from payment_service.infrastructure.models import Base, OutboxModel
from payment_service.infrastructure.unit_of_work import SQLAlchemyUnitOfWork
from payment_service import outbox


@asynccontextmanager
async def isolated_database(url):
    # Polling must see only this test's events, even in a shared test database.
    schema = "test_outbox_" + uuid4().hex
    engine = create_async_engine(
        url, isolation_level="READ COMMITTED",
        execution_options={"schema_translate_map": {None: schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()


async def seed_event(sessions, event_type="payments.new"):
    payment = Payment(
        amount=Decimal("123.45"), currency=Currency.RUB, description="Outbox test",
        idempotency_key=str(uuid4()), webhook_url="https://example.com/hook",
    )
    async with sessions() as session:
        await create_payment(payment, SQLAlchemyUnitOfWork(session))
    async with sessions.begin() as session:
        row = await session.scalar(select(OutboxModel).where(OutboxModel.payment_id == payment.id))
        row.event_type = event_type
        return row.id


async def state(sessions, event_id):
    async with sessions() as session:
        return (await session.execute(
            select(OutboxModel.published_at, OutboxModel.attempts).where(OutboxModel.id == event_id),
        )).one()


async def publish_one(sessions, publisher):
    async with sessions() as session:
        return await publish_next_event(SQLAlchemyUnitOfWork(session), publisher)


def test_success_marks_once_and_empty_outbox_does_not_publish(database_url):
    async def run():
        async with isolated_database(database_url) as sessions:
            publisher = AsyncMock(spec=EventPublisher)
            assert await publish_one(sessions, publisher) is PublicationResult.EMPTY
            publisher.publish.assert_not_awaited()
            event_id = await seed_event(sessions)
            assert await publish_one(sessions, publisher) is PublicationResult.SENT
            published_at, attempts = await state(sessions, event_id)
            assert published_at is not None and published_at.tzinfo is None
            assert attempts == 1
            assert await publish_one(sessions, publisher) is PublicationResult.EMPTY
            publisher.publish.assert_awaited_once()
            assert publisher.publish.call_args.args[0].id == event_id

    asyncio.run(run())


@pytest.mark.parametrize("error", [ConnectionError("broker unavailable"), TimeoutError("no ack")])
def test_failed_publication_is_retained_and_retried(database_url, error):
    async def run():
        async with isolated_database(database_url) as sessions:
            event_id = await seed_event(sessions)
            publisher = AsyncMock(spec=EventPublisher)
            publisher.publish.side_effect = error
            assert await publish_one(sessions, publisher) is PublicationResult.FAILED
            assert await state(sessions, event_id) == (None, 1)

            publisher.publish.side_effect = None
            assert await publish_one(sessions, publisher) is PublicationResult.SENT
            published_at, attempts = await state(sessions, event_id)
            assert published_at is not None and attempts == 2
            assert [call.args[0].id for call in publisher.publish.await_args_list] == [event_id, event_id]

    asyncio.run(run())


def test_parallel_workers_skip_locked_events(database_url):
    async def run():
        async with isolated_database(database_url) as sessions:
            ids = {await seed_event(sessions), await seed_event(sessions)}
            barrier = asyncio.Barrier(2)

            async def hold_lock(event):
                await barrier.wait()

            publisher = AsyncMock(spec=EventPublisher)
            publisher.publish.side_effect = hold_lock
            results = await asyncio.wait_for(asyncio.gather(
                publish_one(sessions, publisher), publish_one(sessions, publisher),
            ), timeout=5)
            assert results == [PublicationResult.SENT, PublicationResult.SENT]
            assert {call.args[0].id for call in publisher.publish.await_args_list} == ids
            for event_id in ids:
                published_at, attempts = await state(sessions, event_id)
                assert published_at is not None and attempts == 1

    asyncio.run(run())


def test_cancellation_releases_lock_and_keeps_event_pending(database_url):
    async def run():
        async with isolated_database(database_url) as sessions:
            event_id = await seed_event(sessions)
            publisher = AsyncMock(spec=EventPublisher)
            publisher.publish.side_effect = asyncio.CancelledError()
            with pytest.raises(asyncio.CancelledError):
                await publish_one(sessions, publisher)
            assert await state(sessions, event_id) == (None, 0)
            publisher.publish.side_effect = None
            assert await publish_one(sessions, publisher) is PublicationResult.SENT

    asyncio.run(run())


def test_worker_loop_recovers_after_a_publish_error(database_url, monkeypatch):
    monkeypatch.setattr(outbox, "POLL_INTERVAL", 0.01)

    async def run():
        async with isolated_database(database_url) as sessions:
            event_id = await seed_event(sessions)
            stop = asyncio.Event()
            calls = 0

            async def publish(event):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise ConnectionError("broker unavailable")
                stop.set()

            publisher = AsyncMock(spec=EventPublisher)
            publisher.publish.side_effect = publish
            await asyncio.wait_for(outbox.publish_pending(sessions, publisher, stop), timeout=3)
            published_at, attempts = await state(sessions, event_id)
            assert published_at is not None and attempts == calls == 2

    asyncio.run(run())


@pytest.fixture
def rabbitmq_url():
    url = os.environ.get("TEST_RABBITMQ_URL")
    if not url:
        pytest.skip("Set TEST_RABBITMQ_URL to an isolated RabbitMQ test broker")
    return url


@pytest.mark.parametrize("declare_before_publish", [False, True])
def test_real_rabbitmq_routes_persistent_confirmed_message(database_url, rabbitmq_url, declare_before_publish):
    async def run():
        queue = RabbitQueue("test.payments." + uuid4().hex, durable=True)
        async with isolated_database(database_url) as sessions:
            event_id = await seed_event(sessions, queue.name)
            async with create_broker(rabbitmq_url) as broker:
                declared = None
                try:
                    publisher = RabbitMQEventPublisher(broker)
                    if not declare_before_publish:
                        assert await publish_one(sessions, publisher) is PublicationResult.FAILED
                        assert await state(sessions, event_id) == (None, 1)
                    declared = await broker.declare_queue(queue)
                    assert await publish_one(sessions, publisher) is PublicationResult.SENT
                    message = await declared.get(timeout=5, fail=True)
                    assert message.message_id == str(event_id)
                    assert message.type == queue.name
                    assert message.delivery_mode == DeliveryMode.PERSISTENT
                    UUID(json.loads(message.body)["payment_id"])
                    await message.ack()
                    published_at, attempts = await state(sessions, event_id)
                    assert published_at is not None
                    assert attempts == (1 if declare_before_publish else 2)
                finally:
                    if declared is not None:
                        await declared.delete(if_unused=False, if_empty=False)

    asyncio.run(run())


def test_ack_followed_by_db_failure_republishes_same_message_id(database_url, rabbitmq_url):
    async def run():
        queue = RabbitQueue("test.payments." + uuid4().hex, durable=True)
        async with isolated_database(database_url) as sessions:
            event_id = await seed_event(sessions, queue.name)
            async with create_broker(rabbitmq_url) as broker:
                declared = await broker.declare_queue(queue)
                try:
                    publisher = RabbitMQEventPublisher(broker)
                    async with sessions() as session:
                        def fail_commit(session):
                            raise RuntimeError("DB commit failed after broker ack")

                        event.listen(session.sync_session, "before_commit", fail_commit)
                        with pytest.raises(RuntimeError, match="DB commit failed"):
                            await publish_next_event(SQLAlchemyUnitOfWork(session), publisher)
                    assert await state(sessions, event_id) == (None, 0)
                    assert await publish_one(sessions, publisher) is PublicationResult.SENT
                    messages = [await declared.get(timeout=5, fail=True) for _ in range(2)]
                    assert [message.message_id for message in messages] == [str(event_id), str(event_id)]
                    for message in messages:
                        await message.ack()
                finally:
                    await declared.delete(if_unused=False, if_empty=False)

    asyncio.run(run())
