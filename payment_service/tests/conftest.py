import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from payment_service.application.repositories import OutboxRepository, PaymentRepository
from payment_service.application.unit_of_work import UnitOfWork


@pytest.fixture(autouse=True)
def database_environment(monkeypatch):
    # Unit tests do not connect to a database unless they enter the app lifespan.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://payments:payments@127.0.0.1:5432/payments",
    )


@pytest.fixture
def database_url(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated test PostgreSQL database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("API_KEY", "test-api-key")
    return url


@pytest.fixture
def unit_of_work():
    work = MagicMock(spec=UnitOfWork)
    work.payments = AsyncMock(spec=PaymentRepository)
    work.payments.add_if_absent.return_value = True
    work.outbox = AsyncMock(spec=OutboxRepository)
    work.__aenter__.return_value = work
    work.__aexit__.return_value = None
    return work
