"""HTTP routes for payment creation and retrieval."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from payment_service.application import handlers
from payment_service.controllers.auth import verify_api_key
from payment_service.controllers.schemas import PaymentCreate, PaymentCreated, PaymentRead
from payment_service.domain.entities import Payment


router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(verify_api_key)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid or missing API key"},
        status.HTTP_501_NOT_IMPLEMENTED: {"description": "Handler is not implemented"},
    },
)

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=r"\S"),
]


@router.post("", response_model=PaymentCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_payment(
    payload: PaymentCreate,
    idempotency_key: IdempotencyKey,
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
async def get_payment(payment_id: UUID) -> Payment:
    return await handlers.get_payment(payment_id)
