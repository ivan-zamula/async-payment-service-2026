"""Payment processing entry points; implementation follows in the next step."""

from uuid import UUID

from payment_service.domain.entities import Payment


async def create_payment(payment: Payment) -> Payment:
    raise NotImplementedError


async def get_payment(payment_id: UUID) -> Payment:
    raise NotImplementedError
