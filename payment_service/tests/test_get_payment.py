import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from payment_service.app import create_app
from payment_service.application.repositories import PaymentRepository
from payment_service.controllers.dependencies import get_payment_repository


@pytest.fixture
def app_and_repository(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-api-key")
    app = create_app()
    repository = AsyncMock(spec=PaymentRepository)
    repository.get_by_id.return_value = None

    async def override_repository():
        return repository

    app.dependency_overrides[get_payment_repository] = override_repository
    return app, repository


def get(app, payment_id):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            return await client.get(
                f"/api/v1/payments/{payment_id}", headers={"X-API-Key": "test-api-key"},
            )

    return asyncio.run(run())


def test_missing_payment_returns_404(app_and_repository):
    app, repository = app_and_repository
    payment_id = uuid4()

    response = get(app, payment_id)

    assert response.status_code == 404
    assert response.json() == {"detail": "Payment not found"}
    repository.get_by_id.assert_awaited_once_with(payment_id)


def test_invalid_uuid_returns_422_without_querying_repository(app_and_repository):
    app, repository = app_and_repository

    response = get(app, "not-a-uuid")

    assert response.status_code == 422
    repository.get_by_id.assert_not_awaited()


def test_openapi_documents_get_responses(app_and_repository):
    app, _ = app_and_repository
    paths = app.openapi()["paths"]
    responses = paths["/api/v1/payments/{payment_id}"]["get"]["responses"]
    assert {"200", "401", "404", "422"} <= responses.keys()
    assert "501" not in responses
    assert "409" in paths["/api/v1/payments"]["post"]["responses"]
    assert "501" not in paths["/api/v1/payments"]["post"]["responses"]
