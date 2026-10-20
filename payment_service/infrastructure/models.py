from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from payment_service.domain.constants import (
    MAX_PAYMENT_AMOUNT,
    MAX_PROCESSING_FAILURES,
    MIN_PAYMENT_AMOUNT,
    PAYMENT_AMOUNT_PRECISION,
    PAYMENT_AMOUNT_SCALE,
)
from payment_service.domain.entities import Currency, PaymentStatus


class Base(AsyncAttrs, DeclarativeBase):
    pass


class PaymentModel(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payments_idempotency_key"),
        CheckConstraint(
            f"amount > {MIN_PAYMENT_AMOUNT} AND amount <= {MAX_PAYMENT_AMOUNT}",
            name="ck_payments_amount",
        ),
        CheckConstraint(
            "btrim(idempotency_key) <> ''", name="ck_payments_idempotency_key",
        ),
        CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="ck_payments_metadata",
        ),
        CheckConstraint(
            "(status = 'pending' AND processed_at IS NULL) OR "
            "(status IN ('succeeded', 'failed') AND processed_at IS NOT NULL)",
            name="ck_payments_status_time",
        ),
        CheckConstraint(
            "processed_at IS NULL OR processed_at >= created_at",
            name="ck_payments_processing_time",
        ),
        CheckConstraint(
            f"processing_failures BETWEEN 0 AND {MAX_PROCESSING_FAILURES}",
            name="ck_payments_processing_failures",
        ),
        CheckConstraint(
            "webhook_sent_at IS NULL OR status IN ('succeeded', 'failed')",
            name="ck_payments_webhook_status",
        ),
        CheckConstraint(
            "webhook_sent_at IS NULL OR dead_lettered_at IS NULL",
            name="ck_payments_delivery_result",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(PAYMENT_AMOUNT_PRECISION, PAYMENT_AMOUNT_SCALE), nullable=False,
    )
    currency: Mapped[Currency] = mapped_column(
        Enum(Currency, native_enum=False, create_constraint=True, name="currency"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # SQLAlchemy reserves the attribute metadata; the SQL column keeps its name.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus, native_enum=False, create_constraint=True,
            name="payment_status",
            values_callable=lambda values: [item.value for item in values],
        ),
        nullable=False, default=PaymentStatus.PENDING, server_default="pending",
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    webhook_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    processing_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    webhook_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))


class OutboxModel(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="ck_outbox_payload"),
        Index(
            "ix_outbox_unpublished", "created_at", "id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    payment_id: Mapped[UUID] = mapped_column(
        ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    # Publication attempts are independent of the consumer's three-attempt budget.
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
