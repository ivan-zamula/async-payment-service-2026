"""Run against a migrated test database selected with TEST_DATABASE_URL."""

import asyncio
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Annotated
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from payment_service.app import create_app
from payment_service.controllers.dependencies import get_session
from payment_service.domain.entities import Currency
from payment_service.infrastructure.database import connect_database
from payment_service.infrastructure.models import OutboxModel, PaymentModel


@pytest.fixture
def database_url(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated test PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("API_KEY", "test-api-key")
    return url


def test_app_lifespan_provides_independent_request_sessions(database_url):
    app = create_app()
    sessions = []

    @app.get("/_test/database")
    async def probe(session: Annotated[AsyncSession, Depends(get_session)]):
        sessions.append(session)
        return {"value": await session.scalar(text("SELECT 1"))}

    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test",
            ) as client:
                for _ in range(2):
                    response = await client.get("/_test/database")
                    assert response.status_code == 200
                    assert response.json() == {"value": 1}
        assert sessions[0] is not sessions[1]

    asyncio.run(run())


def test_session_rolls_back_payment_and_outbox_on_database_error(database_url):
    payment_id, event_id = uuid4(), uuid4()

    async def run():
        async with connect_database(database_url) as session_factory:
            app = create_app()
            app.state.session_factory = session_factory
            request = Request({"type": "http", "app": app})
            with pytest.raises(IntegrityError):
                async with asynccontextmanager(get_session)(request) as session:
                    session.add(PaymentModel(
                        id=payment_id, amount=Decimal("123.45"), currency=Currency.RUB,
                        description="Rollback test", idempotency_key=str(payment_id),
                        webhook_url="https://example.com/hook",
                    ))
                    await session.flush()
                    session.add(OutboxModel(
                        id=event_id, payment_id=payment_id,
                        event_type="payment.created", payload={"payment_id": str(payment_id)},
                    ))
                    await session.flush()
                    # Duplicate idempotency key violates the database constraint.
                    session.add(PaymentModel(
                        amount=Decimal("123.45"), currency=Currency.RUB,
                        description="Duplicate", idempotency_key=str(payment_id),
                        webhook_url="https://example.com/hook",
                    ))
                    await session.flush()

            async with session_factory() as session:
                assert await session.get(PaymentModel, payment_id) is None
                assert await session.get(OutboxModel, event_id) is None
                assert await session.scalar(
                    select(PaymentModel.id).where(PaymentModel.idempotency_key == str(payment_id)),
                ) is None

    asyncio.run(run())
