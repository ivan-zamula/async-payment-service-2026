import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from payment_service.application.errors import PaymentNotFoundError
from payment_service.application.unit_of_work import UnitOfWork
from payment_service.domain.constants import MAX_PROCESSING_FAILURES
from payment_service.domain.entities import Payment, PaymentStatus


logger = logging.getLogger(__name__)
RETRY_BASE_DELAY = 2.0


class PaymentGateway(Protocol):
    async def process(self, payment: Payment) -> bool:
        """Return the business outcome; raise on a technical failure."""
        ...


class WebhookSender(Protocol):
    async def send(self, payment: Payment) -> None:
        """Deliver the final payment result, raising on a failed HTTP request."""
        ...


class ProcessingOutcome(StrEnum):
    DONE = "done"
    RETRY = "retry"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    outcome: ProcessingOutcome
    failures: int = 0


def failure_result(failures: int) -> ProcessingResult:
    outcome = ProcessingOutcome.EXHAUSTED if failures >= MAX_PROCESSING_FAILURES else ProcessingOutcome.RETRY
    return ProcessingResult(outcome, failures)


async def process_payment(
    payment_id: UUID,
    unit_of_work: UnitOfWork,
    gateway: PaymentGateway,
    webhooks: WebhookSender,
) -> ProcessingResult:
    async with unit_of_work:
        state = await unit_of_work.payments.get_for_processing(payment_id)
        if state is None:
            raise PaymentNotFoundError(payment_id)
        if state.completed:
            return ProcessingResult(ProcessingOutcome.DONE, state.failures)
        if state.failures >= MAX_PROCESSING_FAILURES:
            return failure_result(state.failures)
        payment = state.payment
        if payment.status is PaymentStatus.PENDING:
            try:
                succeeded = await gateway.process(payment)
            except Exception:
                logger.exception("Gateway failed: payment_id=%s", payment_id)
                await unit_of_work.payments.record_processing_failure(payment_id)
                return failure_result(state.failures + 1)
            if succeeded:
                payment.succeed()
            else:
                payment.fail()
            await unit_of_work.payments.save_result(payment)

    # Commit the gateway result before performing an HTTP side effect.
    async with unit_of_work:
        state = await unit_of_work.payments.get_for_processing(payment_id)
        if state is None:
            raise PaymentNotFoundError(payment_id)
        if state.completed:
            return ProcessingResult(ProcessingOutcome.DONE, state.failures)
        if state.failures >= MAX_PROCESSING_FAILURES:
            return failure_result(state.failures)
        try:
            await webhooks.send(state.payment)
        except Exception:
            logger.exception("Webhook failed: payment_id=%s", payment_id)
            await unit_of_work.payments.record_processing_failure(payment_id)
            return failure_result(state.failures + 1)
        await unit_of_work.payments.mark_webhook_sent(payment_id)
    return ProcessingResult(ProcessingOutcome.DONE, state.failures)
