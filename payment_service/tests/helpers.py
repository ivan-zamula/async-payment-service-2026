"""Isolated PostgreSQL schema shared by worker integration tests."""

from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from payment_service.infrastructure.models import Base
from payment_service.application.handlers import create_payment
from payment_service.domain.entities import Currency, Payment
from payment_service.infrastructure.unit_of_work import SQLAlchemyUnitOfWork


@asynccontextmanager
async def isolated_database(url):
    schema = "test_payments_" + uuid4().hex
    engine = create_async_engine(
        url, isolation_level="READ COMMITTED",
        execution_options={"schema_translate_map": {None: schema}},
    )
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()


async def seed_payment(sessions):
    payment = Payment(
        amount=Decimal("123.45"), currency=Currency.RUB, description="Consumer test",
        idempotency_key=str(uuid4()), webhook_url="https://example.com/hook",
    )
    async with sessions() as session:
        await create_payment(payment, SQLAlchemyUnitOfWork(session))
    return payment
