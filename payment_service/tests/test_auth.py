import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from payment_service.app import create_app
from payment_service.application import handlers


TEST_API_KEY = "test-api-key"
PAYLOAD = {
    "amount": "123.45",
    "currency": "RUB",
    "description": "Order",
    "webhook_url": "https://example.com/hook",
}


def request(app, method, path, headers=None):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            return await client.request(
                method, path, headers=headers,
                json=PAYLOAD if method == "POST" else None,
            )

    return asyncio.run(send())


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("API_KEY", TEST_API_KEY)
    return create_app()


@pytest.mark.parametrize("method", ["POST", "GET"])
@pytest.mark.parametrize("api_key", [None, "", "wrong-key", " "])
def test_invalid_credentials_do_not_reach_handlers(app, monkeypatch, method, api_key):
    create = AsyncMock()
    get = AsyncMock()
    monkeypatch.setattr(handlers, "create_payment", create)
    monkeypatch.setattr(handlers, "get_payment", get)
    headers = {"Idempotency-Key": "order-1"}
    if api_key is not None:
        headers["X-API-Key"] = api_key
    path = "/api/v1/payments" if method == "POST" else f"/api/v1/payments/{uuid4()}"

    response = request(app, method, path, headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    assert response.headers["www-authenticate"] == "APIKey"
    create.assert_not_awaited()
    get.assert_not_awaited()


@pytest.mark.parametrize("method", ["POST", "GET"])
def test_valid_credentials_reach_the_unimplemented_handler(app, method):
    path = "/api/v1/payments" if method == "POST" else f"/api/v1/payments/{uuid4()}"
    response = request(app, method, path, {
        "X-API-Key": TEST_API_KEY, "Idempotency-Key": "order-1",
    })
    assert response.status_code == 501


@pytest.mark.parametrize("api_key", [None, "", " ", "\t"])
def test_application_requires_a_configured_key(monkeypatch, api_key):
    if api_key is None:
        monkeypatch.delenv("API_KEY", raising=False)
    else:
        monkeypatch.setenv("API_KEY", api_key)
    with pytest.raises(RuntimeError, match="API_KEY"):
        create_app()


def test_each_app_keeps_its_own_configured_key(app, monkeypatch):
    monkeypatch.setenv("API_KEY", "another-test-key")
    another_app = create_app()
    path = f"/api/v1/payments/{uuid4()}"
    assert request(app, "GET", path, {"X-API-Key": TEST_API_KEY}).status_code == 501
    assert request(another_app, "GET", path, {"X-API-Key": TEST_API_KEY}).status_code == 401
    assert request(another_app, "GET", path, {"X-API-Key": "another-test-key"}).status_code == 501


def test_query_parameter_cannot_replace_the_header(app):
    response = request(app, "GET", f"/api/v1/payments/{uuid4()}?api_key={TEST_API_KEY}")
    assert response.status_code == 401


def test_openapi_declares_header_authentication_for_both_routes(app):
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey", "in": "header", "name": "X-API-Key",
    }
    for path, method in (("/api/v1/payments", "post"), ("/api/v1/payments/{payment_id}", "get")):
        operation = schema["paths"][path][method]
        assert operation["security"] == [{"APIKeyHeader": []}]
        assert "401" in operation["responses"]
