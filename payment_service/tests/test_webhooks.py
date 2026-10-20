import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from payment_service.domain.entities import Currency, Payment
from payment_service.infrastructure import gateway as gateway_module
from payment_service.infrastructure.webhooks import HTTPWebhookSender


def payment():
    value = Payment(
        amount=Decimal("123.45"), currency=Currency.RUB, description="Webhook test",
        idempotency_key=str(uuid4()), webhook_url="https://example.com/hook",
    )
    value.succeed()
    return value


@pytest.mark.parametrize("response_status", [200, 204, 302, 400, 500])
def test_webhook_contract_and_http_errors(response_status):
    entity = payment()
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(response_status)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            sender = HTTPWebhookSender(client)
            if response_status >= 300:
                with pytest.raises(httpx.HTTPStatusError):
                    await sender.send(entity)
            else:
                await sender.send(entity)
        assert len(requests) == 1
        assert requests[0].headers["Idempotency-Key"] == str(entity.id)
        assert json.loads(requests[0].content) == {
            "payment_id": str(entity.id), "status": "succeeded", "amount": "123.45",
            "currency": "RUB", "processed_at": entity.processed_at.isoformat(),
        }

    asyncio.run(run())


@pytest.mark.parametrize("random_value,expected", [(0.0, True), (0.899, True), (0.9, False), (0.99, False)])
def test_mock_gateway_probability_boundary(monkeypatch, random_value, expected):
    monkeypatch.setattr(gateway_module.random, "random", lambda: random_value)
    monkeypatch.setattr(gateway_module.random, "uniform", lambda low, high: 3.5)
    sleep = AsyncMock()
    monkeypatch.setattr(gateway_module.asyncio, "sleep", sleep)
    assert asyncio.run(gateway_module.MockPaymentGateway().process(payment())) is expected
    sleep.assert_awaited_once_with(3.5)
