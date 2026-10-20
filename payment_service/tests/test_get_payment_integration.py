import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete

from payment_service.app import create_app
from payment_service.domain.entities import Currency, Payment, PaymentStatus
from payment_service.infrastructure.models import PaymentModel
from payment_service.infrastructure.repositories import SQLAlchemyPaymentRepository


@pytest.mark.parametrize("status", list(PaymentStatus))
def test_get_payment_from_postgresql(database_url, status):
    created_at = datetime(2026, 10, 19, 12, 30)
    payment = Payment(
        amount=Decimal("123.45"), currency=Currency.USD,
        description="Тестовый платеж", idempotency_key=str(uuid4()),
        webhook_url="https://example.com/hook", metadata={"order": {"items": [1, 2]}},
        created_at=created_at,
    )
    if status is PaymentStatus.SUCCEEDED:
        payment.succeed(created_at + timedelta(seconds=3))
    elif status is PaymentStatus.FAILED:
        payment.fail(created_at + timedelta(seconds=3))

    async def run():
        app = create_app()
        async with app.router.lifespan_context(app):
            session_factory = app.state.session_factory
            try:
                async with session_factory.begin() as session:
                    await SQLAlchemyPaymentRepository(session).add(payment)

                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test",
                ) as client:
                    response = await client.get(
                        f"/api/v1/payments/{payment.id}",
                        headers={"X-API-Key": "test-api-key"},
                    )

                assert response.status_code == 200
                assert response.json() == {
                    "payment_id": str(payment.id), "amount": "123.45", "currency": "USD",
                    "description": payment.description, "metadata": {"order": {"items": [1, 2]}},
                    "status": status.value, "idempotency_key": payment.idempotency_key,
                    "webhook_url": payment.webhook_url, "created_at": created_at.isoformat(),
                    "processed_at": payment.processed_at.isoformat() if payment.processed_at else None,
                }
            finally:
                async with session_factory.begin() as session:
                    await session.execute(delete(PaymentModel).where(PaymentModel.id == payment.id))

    asyncio.run(run())
