"""SQLAlchemy implementation of the payment repository."""

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payment_service.application.events import OutboxEvent
from payment_service.application.repositories import OutboxRepository, PaymentRepository
from payment_service.domain.entities import Payment
from payment_service.infrastructure.models import OutboxModel, PaymentModel


class SQLAlchemyPaymentRepository(PaymentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> None:
        self._session.add(PaymentModel(**self._values(payment)))
        # Send INSERT to PostgreSQL; commit/rollback belongs to the caller.
        await self._session.flush()

    async def add_if_absent(self, payment: Payment) -> bool:
        statement = (
            insert(PaymentModel)
            .values(**self._values(payment))
            .on_conflict_do_nothing(constraint="uq_payments_idempotency_key")
            .returning(PaymentModel.id)
        )
        return await self._session.scalar(statement) is not None

    @staticmethod
    def _values(payment: Payment) -> dict[str, Any]:
        return {
            "id": payment.id,
            "amount": payment.amount,
            "currency": payment.currency,
            "description": payment.description,
            "metadata_": deepcopy(payment.metadata),
            "status": payment.status,
            "idempotency_key": payment.idempotency_key,
            "webhook_url": payment.webhook_url,
            "created_at": payment.created_at,
            "processed_at": payment.processed_at,
        }

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


class SQLAlchemyOutboxRepository(OutboxRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_payment_created(self, payment: Payment) -> None:
        self._session.add(OutboxModel(
            payment_id=payment.id,
            event_type="payments.new",
            payload={"payment_id": str(payment.id)},
            created_at=payment.created_at,
        ))
        await self._session.flush()

    async def get_next_unpublished(self) -> OutboxEvent | None:
        row = await self._session.scalar(
            select(OutboxModel)
            .where(OutboxModel.published_at.is_(None))
            .order_by(OutboxModel.created_at, OutboxModel.id)
            .limit(1)
            .with_for_update(skip_locked=True),
        )
        if row is None:
            return None
        return OutboxEvent(id=row.id, event_type=row.event_type, payload=deepcopy(row.payload))

    async def record_attempt(self, event_id: UUID) -> None:
        await self._session.execute(
            update(OutboxModel).where(OutboxModel.id == event_id)
            .values(attempts=OutboxModel.attempts + 1),
        )

    async def mark_published(self, event_id: UUID) -> None:
        await self._session.execute(
            update(OutboxModel).where(OutboxModel.id == event_id)
            .values(published_at=datetime.now()),
        )
