"""PostgreSQL connection pool and async session factory."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import make_url, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def get_database_url() -> str:
    value = os.environ.get("DATABASE_URL", "")
    if not value.strip():
        raise RuntimeError("Set a non-empty DATABASE_URL environment variable")
    try:
        url = make_url(value)
    except (ArgumentError, ValueError):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL asyncpg URL") from None
    if url.drivername != "postgresql+asyncpg" or not url.host or not url.database:
        raise RuntimeError("DATABASE_URL must use postgresql+asyncpg and include host and database")
    return value


@asynccontextmanager
async def connect_database(
    database_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        database_url, pool_pre_ping=True, connect_args={"timeout": 5},
        isolation_level="READ COMMITTED",
    )
    try:
        # Fail at startup if PostgreSQL is unavailable.
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
