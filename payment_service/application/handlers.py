"""Payment creation and retrieval scenarios."""

import json
from uuid import UUID

from payment_service.application.errors import IdempotencyConflictError, PaymentNotFoundError
from payment_service.application.repositories import PaymentRepository
from payment_service.application.unit_of_work import UnitOfWork
from payment_service.domain.entities import Payment


async def create_payment(payment: Payment, unit_of_work: UnitOfWork) -> Payment:
    async with unit_of_work:
        if await unit_of_work.payments.add_if_absent(payment):
            await unit_of_work.outbox.add_payment_created(payment)
            return payment

        existing = await unit_of_work.payments.get_by_idempotency_key(payment.idempotency_key)
        if existing is None:
            raise RuntimeError("Payment disappeared after an idempotency key conflict")
        if not _same_request(existing, payment):
            raise IdempotencyConflictError(payment.idempotency_key)
        return existing


def _same_request(existing: Payment, requested: Payment) -> bool:
    return (
        existing.amount == requested.amount
        and existing.currency == requested.currency
        and existing.description == requested.description
        and existing.webhook_url == requested.webhook_url
        # JSON comparison distinguishes booleans from numbers and ignores key order.
        and json.dumps(existing.metadata, sort_keys=True)
        == json.dumps(requested.metadata, sort_keys=True)
    )


async def get_payment(payment_id: UUID, repository: PaymentRepository) -> Payment:
    payment = await repository.get_by_id(payment_id)
    if payment is None:
        raise PaymentNotFoundError(payment_id)
    return payment
