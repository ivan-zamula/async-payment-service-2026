import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from payment_service.application.processing import (
    PaymentGateway, ProcessingOutcome, WebhookSender, process_payment,
)
from payment_service.domain.entities import PaymentStatus
from payment_service.infrastructure.models import PaymentModel
from payment_service.infrastructure.unit_of_work import SQLAlchemyUnitOfWork
from payment_service.tests.helpers import isolated_database, seed_payment


async def process(sessions, payment, gateway, webhooks):
    async with sessions() as session:
        return await process_payment(payment.id, SQLAlchemyUnitOfWork(session), gateway, webhooks)


async def state(sessions, payment_id):
    async with sessions() as session:
        return (await session.execute(select(
            PaymentModel.status, PaymentModel.processing_failures, PaymentModel.webhook_sent_at,
            PaymentModel.dead_lettered_at, PaymentModel.processed_at,
        ).where(PaymentModel.id == payment_id))).one()


@pytest.mark.parametrize("succeeded", [False, True])
def test_final_result_and_duplicate_delivery(database_url, succeeded):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            gateway = AsyncMock(spec=PaymentGateway)
            gateway.process.return_value = succeeded
            webhooks = AsyncMock(spec=WebhookSender)
            assert (await process(sessions, payment, gateway, webhooks)).outcome is ProcessingOutcome.DONE
            stored = await state(sessions, payment.id)
            assert stored.status is (PaymentStatus.SUCCEEDED if succeeded else PaymentStatus.FAILED)
            assert stored.processed_at is not None and stored.processed_at.tzinfo is None
            assert stored.webhook_sent_at is not None
            assert stored.processing_failures == 0
            assert stored.dead_lettered_at is None
            assert (await process(sessions, payment, gateway, webhooks)).outcome is ProcessingOutcome.DONE
            gateway.process.assert_awaited_once()
            webhooks.send.assert_awaited_once()

    asyncio.run(run())


def test_webhook_retry_preserves_gateway_result(database_url):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            gateway = AsyncMock(spec=PaymentGateway)
            gateway.process.return_value = True
            webhooks = AsyncMock(spec=WebhookSender)
            webhooks.send.side_effect = [TimeoutError("webhook unavailable"), None]
            first = await process(sessions, payment, gateway, webhooks)
            assert first.outcome is ProcessingOutcome.RETRY and first.failures == 1
            before = await state(sessions, payment.id)
            assert before.status is PaymentStatus.SUCCEEDED and before.webhook_sent_at is None
            assert (await process(sessions, payment, gateway, webhooks)).outcome is ProcessingOutcome.DONE
            after = await state(sessions, payment.id)
            assert after.processed_at == before.processed_at
            assert after.processing_failures == 1 and after.webhook_sent_at is not None
            gateway.process.assert_awaited_once()
            assert webhooks.send.await_count == 2

    asyncio.run(run())


def test_gateway_technical_failure_keeps_payment_pending(database_url):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            gateway = AsyncMock(spec=PaymentGateway)
            gateway.process.side_effect = [ConnectionError("gateway unavailable"), True]
            webhooks = AsyncMock(spec=WebhookSender)
            result = await process(sessions, payment, gateway, webhooks)
            assert result.outcome is ProcessingOutcome.RETRY and result.failures == 1
            stored = await state(sessions, payment.id)
            assert stored.status is PaymentStatus.PENDING and stored.processed_at is None
            webhooks.send.assert_not_awaited()
            assert (await process(sessions, payment, gateway, webhooks)).outcome is ProcessingOutcome.DONE

    asyncio.run(run())


def test_failure_budget_survives_new_sessions(database_url):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)
            gateway = AsyncMock(spec=PaymentGateway)
            gateway.process.return_value = True
            webhooks = AsyncMock(spec=WebhookSender)
            webhooks.send.side_effect = TimeoutError("webhook unavailable")
            for failures in range(1, 4):
                result = await process(sessions, payment, gateway, webhooks)
                assert result.failures == failures
            assert result.outcome is ProcessingOutcome.EXHAUSTED
            assert (await process(sessions, payment, gateway, webhooks)).outcome is ProcessingOutcome.EXHAUSTED
            assert webhooks.send.await_count == 3
            gateway.process.assert_awaited_once()
            assert (await state(sessions, payment.id)).processing_failures == 3

    asyncio.run(run())


def test_concurrent_duplicate_does_not_repeat_gateway_or_webhook(database_url):
    async def run():
        async with isolated_database(database_url) as sessions:
            payment = await seed_payment(sessions)

            async def gateway_call(payment):
                await asyncio.sleep(0.01)
                return True

            gateway = AsyncMock(spec=PaymentGateway)
            gateway.process.side_effect = gateway_call
            webhooks = AsyncMock(spec=WebhookSender)
            results = await asyncio.wait_for(asyncio.gather(
                process(sessions, payment, gateway, webhooks),
                process(sessions, payment, gateway, webhooks),
            ), timeout=5)
            assert all(result.outcome is ProcessingOutcome.DONE for result in results)
            gateway.process.assert_awaited_once()
            webhooks.send.assert_awaited_once()

    asyncio.run(run())
