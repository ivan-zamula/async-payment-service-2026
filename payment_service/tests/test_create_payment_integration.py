import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Depends
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.app import create_app
from payment_service.controllers.dependencies import get_session, get_unit_of_work
from payment_service.domain.entities import PaymentStatus
from payment_service.infrastructure.models import OutboxModel, PaymentModel
from payment_service.infrastructure.repositories import (
    SQLAlchemyOutboxRepository,
    SQLAlchemyPaymentRepository,
)
from payment_service.infrastructure.unit_of_work import SQLAlchemyUnitOfWork


PAYLOAD = {
    "amount": "123.45", "currency": "RUB", "description": "Order",
    "metadata": {"order_id": 42, "items": [1, 2]},
    "webhook_url": "https://example.com/hook",
}


@asynccontextmanager
async def payment_api(key):
    app = create_app()
    async with app.router.lifespan_context(app):
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
                headers={"X-API-Key": "test-api-key", "Idempotency-Key": key},
            ) as client:
                yield app, client
        finally:
            async with app.state.session_factory.begin() as session:
                ids = select(PaymentModel.id).where(PaymentModel.idempotency_key == key)
                await session.execute(delete(OutboxModel).where(OutboxModel.payment_id.in_(ids)))
                await session.execute(delete(PaymentModel).where(PaymentModel.idempotency_key == key))


async def assert_database(app, key, count=1):
    async with app.state.session_factory() as session:
        payments = (await session.scalars(
            select(PaymentModel).where(PaymentModel.idempotency_key == key),
        )).all()
        events = (await session.scalars(
            select(OutboxModel).join(PaymentModel).where(PaymentModel.idempotency_key == key),
        )).all()
        assert len(payments) == len(events) == count
        if count:
            assert events[0].payment_id == payments[0].id
            assert events[0].event_type == "payments.new"
            assert events[0].payload == {"payment_id": str(payments[0].id)}
            assert events[0].published_at is None
            assert events[0].attempts == 0


def test_create_payment_and_read_it_back(database_url):
    async def run():
        key = str(uuid4())
        async with payment_api(key) as (app, client):
            response = await client.post("/api/v1/payments", json=PAYLOAD)
            assert response.status_code == 202
            created = response.json()
            assert set(created) == {"payment_id", "status", "created_at"}
            UUID(created["payment_id"])
            assert created["status"] == "pending"
            assert datetime.fromisoformat(created["created_at"]).tzinfo is None

            response = await client.get(f"/api/v1/payments/{created['payment_id']}")
            assert response.status_code == 200
            assert response.json() == PAYLOAD | created | {
                "idempotency_key": key, "processed_at": None,
            }
            await assert_database(app, key)

    asyncio.run(run())


@pytest.mark.parametrize("status", list(PaymentStatus))
def test_repeated_request_returns_existing_payment(database_url, status):
    async def run():
        key = str(uuid4())
        async with payment_api(key) as (app, client):
            first = await client.post("/api/v1/payments", json=PAYLOAD)
            assert first.status_code == 202
            created = first.json()
            if status is not PaymentStatus.PENDING:
                async with app.state.session_factory.begin() as session:
                    row = await session.get(PaymentModel, UUID(created["payment_id"]))
                    row.status = status
                    row.processed_at = row.created_at + timedelta(seconds=3)

            # Equivalent decimal and reordered JSON keys are still the same request.
            body = PAYLOAD | {"amount": "123.450", "metadata": dict(reversed(PAYLOAD["metadata"].items()))}
            second = await client.post("/api/v1/payments", json=body)
            assert second.status_code == 202
            assert second.json() == created | {"status": status.value}
            await assert_database(app, key)

    asyncio.run(run())


@pytest.mark.parametrize("changes", [
    {"amount": "456.78"}, {"currency": "USD"}, {"description": "Another order"},
    {"metadata": {"order_id": 43}}, {"webhook_url": "https://example.com/another"},
    {"metadata": {"order_id": 42, "items": [True, 2]}},
])
def test_reused_key_with_different_data_returns_409(database_url, changes):
    async def run():
        key = str(uuid4())
        async with payment_api(key) as (app, client):
            first = await client.post("/api/v1/payments", json=PAYLOAD)
            assert first.status_code == 202
            response = await client.post("/api/v1/payments", json=PAYLOAD | changes)
            assert response.status_code == 409
            assert response.json() == {"detail": "Idempotency key already used for a different payment"}
            stored = await client.get(f"/api/v1/payments/{first.json()['payment_id']}")
            assert stored.json()["amount"] == PAYLOAD["amount"]
            assert stored.json()["metadata"] == PAYLOAD["metadata"]
            await assert_database(app, key)

    asyncio.run(run())


@pytest.mark.parametrize("different_data", [False, True])
def test_concurrent_requests_create_one_payment_and_event(database_url, monkeypatch, different_data):
    async def run():
        barrier = asyncio.Barrier(2)
        original = SQLAlchemyPaymentRepository.add_if_absent

        async def simultaneous_insert(repository, payment):
            await asyncio.wait_for(barrier.wait(), timeout=5)
            return await original(repository, payment)

        monkeypatch.setattr(SQLAlchemyPaymentRepository, "add_if_absent", simultaneous_insert)
        key = str(uuid4())
        async with payment_api(key) as (app, client):
            other_body = PAYLOAD | {"amount": "456.78"} if different_data else PAYLOAD
            responses = await asyncio.wait_for(asyncio.gather(
                client.post("/api/v1/payments", json=PAYLOAD),
                client.post("/api/v1/payments", json=other_body),
            ), timeout=10)
            assert sorted(response.status_code for response in responses) == (
                [202, 409] if different_data else [202, 202]
            )
            if not different_data:
                assert responses[0].json() == responses[1].json()
            await assert_database(app, key)

    asyncio.run(run())


@pytest.mark.parametrize("failure_stage", ["outbox", "commit"])
def test_failure_rolls_back_both_records_and_allows_retry(database_url, monkeypatch, failure_stage):
    original = SQLAlchemyOutboxRepository.add_payment_created

    async def fail_after_outbox_insert(repository, payment):
        await original(repository, payment)
        raise RuntimeError("Outbox write failed")

    async def failing_unit_of_work(session: Annotated[AsyncSession, Depends(get_session)]):
        def fail_commit(session):
            raise RuntimeError("Commit failed")

        event.listen(session.sync_session, "before_commit", fail_commit)
        return SQLAlchemyUnitOfWork(session)

    async def run():
        key = str(uuid4())
        async with payment_api(key) as (app, client):
            if failure_stage == "outbox":
                monkeypatch.setattr(SQLAlchemyOutboxRepository, "add_payment_created", fail_after_outbox_insert)
            else:
                app.dependency_overrides[get_unit_of_work] = failing_unit_of_work

            response = await client.post("/api/v1/payments", json=PAYLOAD)
            assert response.status_code == 500
            await assert_database(app, key, count=0)

            monkeypatch.setattr(SQLAlchemyOutboxRepository, "add_payment_created", original)
            app.dependency_overrides.clear()
            retry = await client.post("/api/v1/payments", json=PAYLOAD)
            assert retry.status_code == 202
            await assert_database(app, key)

    asyncio.run(run())
