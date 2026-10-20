"""Asynchronous mock payment gateway required by the assignment."""

import asyncio
import random

from payment_service.application.processing import PaymentGateway
from payment_service.domain.entities import Payment


class MockPaymentGateway(PaymentGateway):
    async def process(self, payment: Payment) -> bool:
        await asyncio.sleep(random.uniform(2, 5))
        return random.random() < 0.9
