"""Pydantic v2 schemas for the payment HTTP contract."""

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    NaiveDatetime,
    model_validator,
)

from payment_service.domain.constants import (
    MAX_PAYMENT_AMOUNT,
    MIN_PAYMENT_AMOUNT,
    PAYMENT_AMOUNT_PRECISION,
    PAYMENT_AMOUNT_SCALE,
)
from payment_service.domain.entities import Currency, PaymentStatus


Amount = Annotated[
    Decimal,
    Field(
        gt=MIN_PAYMENT_AMOUNT,
        le=MAX_PAYMENT_AMOUNT,
        max_digits=PAYMENT_AMOUNT_PRECISION,
        decimal_places=PAYMENT_AMOUNT_SCALE,
        allow_inf_nan=False,
    ),
]


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    amount: Amount
    currency: Currency
    description: str = Field(strict=True)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    webhook_url: HttpUrl


class PaymentCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID = Field(validation_alias=AliasChoices("payment_id", "id"))
    status: Literal[PaymentStatus.PENDING] = PaymentStatus.PENDING
    created_at: NaiveDatetime


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, allow_inf_nan=False)

    payment_id: UUID = Field(validation_alias=AliasChoices("payment_id", "id"))
    amount: Amount
    currency: Currency
    description: str
    # Prefer metadata_ when validating an ORM object, avoiding Base.metadata.
    metadata: dict[str, JsonValue] = Field(
        validation_alias=AliasChoices("metadata_", "metadata"),
    )
    status: PaymentStatus
    idempotency_key: str
    webhook_url: HttpUrl
    created_at: NaiveDatetime
    processed_at: NaiveDatetime | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status is PaymentStatus.PENDING:
            if self.processed_at is not None:
                raise ValueError("Pending payment cannot have processed_at")
        elif self.processed_at is None or self.processed_at < self.created_at:
            raise ValueError("Completed payment requires a valid processed_at")
        return self
