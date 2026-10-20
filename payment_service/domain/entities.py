from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from payment_service.domain.constants import (
    MAX_PAYMENT_AMOUNT,
    MIN_PAYMENT_AMOUNT,
    PAYMENT_AMOUNT_PRECISION,
    PAYMENT_AMOUNT_QUANTUM,
    PAYMENT_AMOUNT_SCALE,
)


class Currency(StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True, kw_only=True)
class Payment:
    amount: Decimal
    currency: Currency
    description: str
    idempotency_key: str
    webhook_url: str
    id: UUID = field(default_factory=uuid4)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: PaymentStatus = PaymentStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    processed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise ValueError("Payment ID must be a UUID")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise ValueError("Amount must be a finite Decimal")
        if not MIN_PAYMENT_AMOUNT < self.amount <= MAX_PAYMENT_AMOUNT:
            raise ValueError(
                "Amount must be positive and fit "
                f"NUMERIC({PAYMENT_AMOUNT_PRECISION},{PAYMENT_AMOUNT_SCALE})"
            )
        with localcontext() as context:
            context.prec = PAYMENT_AMOUNT_PRECISION + PAYMENT_AMOUNT_SCALE
            normalized = self.amount.quantize(PAYMENT_AMOUNT_QUANTUM)
        if normalized != self.amount:
            raise ValueError(
                f"Amount cannot have more than {PAYMENT_AMOUNT_SCALE} decimal places"
            )
        self.amount = normalized
        self.currency = Currency(self.currency)
        self.status = PaymentStatus(self.status)
        if not isinstance(self.description, str):
            raise ValueError("Description must be a string")
        if (not isinstance(self.idempotency_key, str)
                or not self.idempotency_key.strip() or len(self.idempotency_key) > 255):
            raise ValueError("Idempotency key must contain 1 to 255 characters")
        if not isinstance(self.metadata, dict):
            raise ValueError("Metadata must be a JSON object")
        self.metadata = deepcopy(self.metadata)
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is not None:
            raise ValueError("created_at must be a datetime without a timezone")
        if self.status is PaymentStatus.PENDING:
            if self.processed_at is not None:
                raise ValueError("Pending payment cannot have processed_at")
        elif self.processed_at is None:
            raise ValueError("Completed payment requires processed_at")
        else:
            self.processed_at = self._processing_time(self.processed_at)

    def succeed(self, processed_at: datetime | None = None) -> None:
        self._finish(PaymentStatus.SUCCEEDED, processed_at)

    def fail(self, processed_at: datetime | None = None) -> None:
        self._finish(PaymentStatus.FAILED, processed_at)

    def _finish(self, status: PaymentStatus, processed_at: datetime | None) -> None:
        if self.status is not PaymentStatus.PENDING:
            raise ValueError("Payment already has a final result")
        timestamp = self._processing_time(
            processed_at if processed_at is not None else datetime.now(),
        )
        self.status = status
        self.processed_at = timestamp

    def _processing_time(self, value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.utcoffset() is not None:
            raise ValueError("processed_at must be a datetime without a timezone")
        if value < self.created_at:
            raise ValueError("processed_at cannot precede created_at")
        return value
