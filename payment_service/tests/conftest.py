import os

import pytest


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
