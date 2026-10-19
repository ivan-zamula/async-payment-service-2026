"""Repository contract checks against a migrated PostgreSQL test database."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from payment_service.domain.entities import Currency, Payment, PaymentStatus
from payment_service.infrastructure.database import connect_database
from payment_service.infrastructure.models import PaymentModel
from payment_service.infrastructure.repositories import SQLAlchemyPaymentRepository


def make_payment(**changes):
    values = dict(
        amount=Decimal("9999999999999999.99"), currency=Currency.RUB,
        description="Тестовый платеж", idempotency_key=str(uuid4()),
        webhook_url="https://example.com/hook", metadata={"order": {"items": [1, 2]}},
    )
    return Payment(**(values | changes))


@pytest.mark.parametrize("currency,status", [
    (Currency.RUB, PaymentStatus.PENDING),
    (Currency.USD, PaymentStatus.SUCCEEDED),
    (Currency.EUR, PaymentStatus.FAILED),
])
def test_committed_payment_roundtrip(database_url, currency, status):
    payment = make_payment(currency=currency)
    if status is PaymentStatus.SUCCEEDED:
        payment.succeed()
    elif status is PaymentStatus.FAILED:
        payment.fail()

    async def run():
        async with connect_database(database_url) as session_factory:
            try:
                async with session_factory.begin() as session:
                    await SQLAlchemyPaymentRepository(session).add(payment)

                # A fresh session reads the committed row from PostgreSQL.
                async with session_factory() as session:
                    repository = SQLAlchemyPaymentRepository(session)
                    by_id = await repository.get_by_id(payment.id)
                    by_key = await repository.get_by_idempotency_key(payment.idempotency_key)
                    assert by_id == payment
                    assert by_key == payment
                    assert by_id.created_at.tzinfo is None
                    if by_id.processed_at is not None:
                        assert by_id.processed_at.tzinfo is None
                    # Returned entities do not share their mutable JSON data.
                    by_id.metadata["order"]["items"].append(3)
                    assert by_key.metadata == payment.metadata
            finally:
                async with session_factory.begin() as session:
                    await session.execute(delete(PaymentModel).where(PaymentModel.id == payment.id))

    asyncio.run(run())


def test_missing_payment_returns_none(database_url):
    async def run():
        async with connect_database(database_url) as session_factory:
            async with session_factory() as session:
                repository = SQLAlchemyPaymentRepository(session)
                assert await repository.get_by_id(uuid4()) is None
                assert await repository.get_by_idempotency_key(str(uuid4())) is None

    asyncio.run(run())


def test_add_does_not_commit_and_session_close_rolls_back(database_url):
    payment = make_payment()

    async def run():
        async with connect_database(database_url) as session_factory:
            async with session_factory() as writer:
                repository = SQLAlchemyPaymentRepository(writer)
                await repository.add(payment)
                assert await repository.get_by_id(payment.id) == payment
                async with session_factory() as reader:
                    assert await SQLAlchemyPaymentRepository(reader).get_by_id(payment.id) is None

            async with session_factory() as reader:
                assert await SQLAlchemyPaymentRepository(reader).get_by_id(payment.id) is None

    asyncio.run(run())


def test_duplicate_key_rolls_back_transaction(database_url):
    first = make_payment()
    duplicate = make_payment(idempotency_key=first.idempotency_key)

    async def run():
        async with connect_database(database_url) as session_factory:
            with pytest.raises(IntegrityError):
                async with session_factory.begin() as session:
                    repository = SQLAlchemyPaymentRepository(session)
                    await repository.add(first)
                    await repository.add(duplicate)

            async with session_factory() as session:
                repository = SQLAlchemyPaymentRepository(session)
                assert await repository.get_by_id(first.id) is None
                assert await repository.get_by_id(duplicate.id) is None
                assert await repository.get_by_idempotency_key(first.idempotency_key) is None

    asyncio.run(run())
