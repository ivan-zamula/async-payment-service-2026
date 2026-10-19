import pytest


@pytest.fixture(autouse=True)
def database_environment(monkeypatch):
    # Unit tests do not connect to a database unless they enter the app lifespan.
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+asyncpg://payments:payments@127.0.0.1:5432/payments",
    )
