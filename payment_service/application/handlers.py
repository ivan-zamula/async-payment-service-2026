"""Payment creation and retrieval scenarios."""

from uuid import UUID

from payment_service.application.errors import PaymentNotFoundError
from payment_service.application.repositories import PaymentRepository
from payment_service.domain.entities import Payment


async def create_payment(payment: Payment) -> Payment:
    raise NotImplementedError


async def get_payment(payment_id: UUID, repository: PaymentRepository) -> Payment:
    payment = await repository.get_by_id(payment_id)
    if payment is None:
        raise PaymentNotFoundError(payment_id)
    return payment
