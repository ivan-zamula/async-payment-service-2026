import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from payment_service.controllers.dependencies import get_session
from payment_service.infrastructure import database


@pytest.mark.parametrize("value", [
    None, "", " ", "not-a-url", "sqlite+aiosqlite:///test.db",
    "postgresql://user:password@localhost/payments",
    "postgresql+asyncpg://user:password@localhost",
    "postgresql+asyncpg://user:password@localhost:bad/payments",
])
def test_invalid_database_configuration(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DATABASE_URL")
    else:
        monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(RuntimeError, match="DATABASE_URL") as error:
        database.get_database_url()
    assert "password" not in str(error.value)


def test_pool_is_disposed_when_startup_connection_fails(monkeypatch):
    engine = MagicMock()
    engine.connect.return_value.__aenter__ = AsyncMock(side_effect=OSError("unavailable"))
    engine.dispose = AsyncMock()
    monkeypatch.setattr(database, "create_async_engine", lambda *args, **kwargs: engine)

    async def run():
        with pytest.raises(OSError, match="unavailable"):
            async with database.connect_database(database.get_database_url()):
                pytest.fail("Application must not start without a database")
        engine.dispose.assert_awaited_once()

    asyncio.run(run())


def test_request_session_context_is_closed_on_handler_error():
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=object())
    session_context.__aexit__ = AsyncMock(return_value=False)
    app = FastAPI()
    app.state.session_factory = MagicMock(return_value=session_context)
    request = Request({"type": "http", "app": app})

    async def run():
        with pytest.raises(ValueError, match="handler failed"):
            async with asynccontextmanager(get_session)(request):
                raise ValueError("handler failed")
        session_context.__aexit__.assert_awaited_once()
        assert session_context.__aexit__.call_args.args[0] is ValueError

    asyncio.run(run())
