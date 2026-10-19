"""SQLAlchemy implementation of the payment repository."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.application.repositories import PaymentRepository
from payment_service.domain.entities import Payment
from payment_service.infrastructure.models import PaymentModel


class SQLAlchemyPaymentRepository(PaymentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> None:
        self._session.add(PaymentModel(
            id=payment.id,
            amount=payment.amount,
            currency=payment.currency,
            description=payment.description,
            metadata_=deepcopy(payment.metadata),
            status=payment.status,
            idempotency_key=payment.idempotency_key,
            webhook_url=payment.webhook_url,
            created_at=payment.created_at,
            processed_at=payment.processed_at,
        ))
        # Send INSERT to PostgreSQL; commit/rollback belongs to the caller.
        await self._session.flush()

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        row = await self._session.get(PaymentModel, payment_id)
        return self._to_entity(row) if row is not None else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        row = await self._session.scalar(
            select(PaymentModel).where(PaymentModel.idempotency_key == idempotency_key),
        )
        return self._to_entity(row) if row is not None else None

    @staticmethod
    def _to_entity(row: PaymentModel) -> Payment:
        return Payment(
            id=row.id,
            amount=row.amount,
            currency=row.currency,
            description=row.description,
            metadata=row.metadata_,
            status=row.status,
            idempotency_key=row.idempotency_key,
            webhook_url=row.webhook_url,
            created_at=row.created_at,
            processed_at=row.processed_at,
        )
