"""HTTP routes for payment creation and retrieval."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from payment_service.application import handlers
from payment_service.application.repositories import PaymentRepository
from payment_service.application.unit_of_work import UnitOfWork
from payment_service.controllers.auth import verify_api_key
from payment_service.controllers.dependencies import get_payment_repository, get_unit_of_work
from payment_service.controllers.schemas import PaymentCreate, PaymentCreated, PaymentRead
from payment_service.domain.entities import Payment


router = APIRouter(
    prefix="/payments",
    tags=["payments"],
    dependencies=[Depends(verify_api_key)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid or missing API key"},
    },
)

IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=255, pattern=r"\S"),
]


@router.post(
    "", response_model=PaymentCreated, status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_409_CONFLICT: {"description": "Idempotency key reused with different data"}},
)
async def create_payment(
    payload: PaymentCreate,
    idempotency_key: IdempotencyKey,
    unit_of_work: Annotated[UnitOfWork, Depends(get_unit_of_work)],
) -> Payment:
    payment = Payment(
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
        metadata=payload.metadata,
        webhook_url=str(payload.webhook_url),
        idempotency_key=idempotency_key,
    )
    return await handlers.create_payment(payment, unit_of_work)


@router.get(
    "/{payment_id}", response_model=PaymentRead,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Payment not found"}},
)
async def get_payment(
    payment_id: UUID,
    repository: Annotated[PaymentRepository, Depends(get_payment_repository)],
) -> Payment:
    return await handlers.get_payment(payment_id, repository)
