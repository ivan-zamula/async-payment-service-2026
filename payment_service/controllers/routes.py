"""HTTP routes for payment creation and retrieval."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, status

from payment_service.application import handlers
from payment_service.controllers.schemas import PaymentCreate, PaymentCreated, PaymentRead
from payment_service.domain.entities import Payment


router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "Handler is not implemented"}},
)

# The header is declared now; checking its configured value is a separate step.
ApiKey = Annotated[str, Header(alias="X-API-Key", min_length=1)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=r"\S"),
]


@router.post("", response_model=PaymentCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_payment(
    payload: PaymentCreate,
    idempotency_key: IdempotencyKey,
    api_key: ApiKey,
) -> Payment:
    payment = Payment(
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        metadata=payload.metadata,
        webhook_url=str(payload.webhook_url),
        idempotency_key=idempotency_key,
    )
    return await handlers.create_payment(payment)


@router.get("/{payment_id}", response_model=PaymentRead)
async def get_payment(payment_id: UUID, api_key: ApiKey) -> Payment:
    return await handlers.get_payment(payment_id)
