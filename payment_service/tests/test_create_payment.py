import asyncio

import httpx
import pytest

from payment_service.app import create_app
from payment_service.controllers.dependencies import get_unit_of_work


PAYLOAD = {
    "amount": "123.45", "currency": "RUB", "description": "Order",
    "metadata": {"order_id": 42}, "webhook_url": "https://example.com/hook",
}


@pytest.mark.parametrize("key,changes", [
    (None, {}), ("", {}), ("   ", {}), ("x" * 256, {}),
    ("order-1", {"amount": "0"}), ("order-1", {"amount": "1.001"}),
    ("order-1", {"currency": "GBP"}), ("order-1", {"webhook_url": "ftp://example.com"}),
    ("order-1", {"status": "succeeded"}),
])
def test_invalid_request_does_not_start_transaction(monkeypatch, unit_of_work, key, changes):
    monkeypatch.setenv("API_KEY", "test-api-key")
    app = create_app()

    async def override():
        return unit_of_work

    app.dependency_overrides[get_unit_of_work] = override

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            headers = {"X-API-Key": "test-api-key"}
            if key is not None:
                headers["Idempotency-Key"] = key
            response = await client.post("/api/v1/payments", headers=headers, json=PAYLOAD | changes)
            assert response.status_code == 422
        unit_of_work.__aenter__.assert_not_awaited()
        unit_of_work.payments.add_if_absent.assert_not_awaited()
        unit_of_work.outbox.add_payment_created.assert_not_awaited()

    asyncio.run(run())
