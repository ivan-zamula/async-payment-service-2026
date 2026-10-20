"""HTTP notification of final payment results."""

import asyncio
from decimal import Decimal
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, NaiveDatetime

from payment_service.application.processing import WebhookSender
from payment_service.domain.entities import Currency, Payment, PaymentStatus


WEBHOOK_TIMEOUT = 5.0


class PaymentResult(BaseModel):
    payment_id: UUID
    status: Literal[PaymentStatus.SUCCEEDED, PaymentStatus.FAILED]
    amount: Decimal
    currency: Currency
    processed_at: NaiveDatetime


class HTTPWebhookSender(WebhookSender):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def send(self, payment: Payment) -> None:
        payload = PaymentResult(
            payment_id=payment.id, status=payment.status, amount=payment.amount,
            currency=payment.currency, processed_at=payment.processed_at,
        )
        async with asyncio.timeout(WEBHOOK_TIMEOUT):
            response = await self._client.post(
                payment.webhook_url, json=payload.model_dump(mode="json"),
                headers={"Idempotency-Key": str(payment.id)},
                timeout=WEBHOOK_TIMEOUT, follow_redirects=False,
            )
            response.raise_for_status()
