from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from payment_service.controllers.schemas import PaymentCreate, PaymentCreated, PaymentRead
from payment_service.domain.entities import Currency, Payment, PaymentStatus
from payment_service.infrastructure.models import Base, PaymentModel


NOW = datetime(2026, 1, 1)


def payment(**changes):
    values = dict(
        amount=Decimal("123.45"), currency=Currency.RUB, description="Order",
        idempotency_key="order-1", webhook_url="https://example.com/hook",
        created_at=NOW,
    )
    return Payment(**(values | changes))


@pytest.mark.parametrize("amount", ["0", "-1", "1.001", "NaN", "Infinity", "10000000000000000"])
def test_domain_rejects_invalid_amounts(amount):
    with pytest.raises(ValueError):
        payment(amount=Decimal(amount))


@pytest.mark.parametrize("success", [True, False])
def test_payment_gets_a_final_result_only_once(success):
    entity = payment()
    if success:
        entity.succeed(NOW + timedelta(seconds=3))
    else:
        entity.fail(NOW + timedelta(seconds=3))
    assert entity.status is (PaymentStatus.SUCCEEDED if success else PaymentStatus.FAILED)
    assert entity.processed_at == NOW + timedelta(seconds=3)
    with pytest.raises(ValueError):
        entity.succeed(NOW + timedelta(seconds=4))
    with pytest.raises(ValueError):
        entity.fail(NOW + timedelta(seconds=4))


def test_invalid_time_does_not_change_payment_state():
    entity = payment()
    with pytest.raises(ValueError):
        entity.succeed(NOW - timedelta(seconds=1))
    assert entity.status is PaymentStatus.PENDING
    assert entity.processed_at is None
    with pytest.raises(ValueError):
        payment(created_at=NOW.replace(tzinfo=timezone(timedelta(hours=3))))


def test_default_dates_have_no_timezone():
    entity = Payment(
        amount=Decimal("123.45"), currency=Currency.RUB, description="Order",
        idempotency_key="order-default-date", webhook_url="https://example.com/hook",
    )
    entity.succeed()
    assert entity.created_at.tzinfo is None
    assert entity.processed_at.tzinfo is None
    assert entity.processed_at >= entity.created_at


def test_schemas_reject_timezone_aware_dates():
    data = PaymentRead.model_validate(payment()).model_dump()
    aware = NOW.replace(tzinfo=timezone(timedelta(hours=3)))
    with pytest.raises(ValidationError):
        PaymentRead.model_validate(data | {"created_at": aware})
    with pytest.raises(ValidationError):
        PaymentRead.model_validate(data | {"status": "succeeded", "processed_at": aware})
    with pytest.raises(ValidationError):
        PaymentCreated(payment_id=uuid4(), created_at=aware)


@pytest.mark.parametrize("changes", [
    {"amount": "0"}, {"amount": "1.001"}, {"amount": "NaN"},
    {"amount": True}, {"currency": "GBP"}, {"status": "succeeded"},
    {"metadata": None}, {"metadata": {"bad": float("nan")}},
    {"webhook_url": "ftp://example.com/hook"},
])
def test_pydantic_rejects_invalid_requests(changes):
    data = dict(amount="123.45", currency="RUB", description="Order",
                webhook_url="https://example.com/hook")
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(data | changes)


def test_decimal_json_roundtrip_and_independent_metadata_defaults():
    data = dict(amount="9999999999999999.99", currency="EUR", description="Order",
                webhook_url="https://example.com/hook")
    first = PaymentCreate(**data)
    second = PaymentCreate(**data)
    first.metadata["order"] = 1
    assert second.metadata == {}
    assert first.amount == Decimal("9999999999999999.99")
    assert first.model_dump(mode="json")["amount"] == "9999999999999999.99"
    assert PaymentCreate.model_validate_json(first.model_dump_json()) == first


def test_response_accepts_the_entity_and_orm_metadata_alias():
    entity = payment(metadata={"order": 1})
    created = PaymentCreated.model_validate(entity)
    assert created.payment_id == entity.id
    assert created.model_dump(mode="json")["status"] == "pending"
    assert PaymentRead.model_validate(entity).metadata == {"order": 1}
    row = PaymentModel(
        id=uuid4(), amount=entity.amount, currency=entity.currency,
        description=entity.description, metadata_={"order": 2}, status=entity.status,
        idempotency_key=entity.idempotency_key, webhook_url=entity.webhook_url,
        created_at=entity.created_at,
    )
    response = PaymentRead.model_validate(row).model_dump(mode="json")
    assert response["metadata"] == {"order": 2}
    assert "metadata_" not in response
    assert "payment_id" in response and "id" not in response


def test_completed_response_requires_processing_time():
    data = PaymentRead.model_validate(payment()).model_dump()
    with pytest.raises(ValidationError):
        PaymentRead.model_validate(data | {"status": "succeeded"})


def test_models_compile_as_postgresql_tables():
    tables = {table.name: str(CreateTable(table).compile(dialect=dialect()))
              for table in Base.metadata.sorted_tables}
    assert set(tables) == {"payments", "outbox"}
    assert "NUMERIC(18, 2)" in tables["payments"]
    assert "JSONB" in tables["payments"]
    assert "UNIQUE (idempotency_key)" in tables["payments"]
    assert "REFERENCES payments (id)" in tables["outbox"]
    for ddl in tables.values():
        assert "TIMESTAMP WITHOUT TIME ZONE" in ddl
        assert "TIMESTAMP WITH TIME ZONE" not in ddl
