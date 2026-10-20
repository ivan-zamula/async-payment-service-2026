from dataclasses import dataclass
from datetime import datetime

from payment_service.domain.entities import Payment


@dataclass(frozen=True, slots=True)
class PaymentProcessingState:
    payment: Payment
    failures: int
    webhook_sent_at: datetime | None
    dead_lettered_at: datetime | None

    @property
    def completed(self) -> bool:
        return self.webhook_sent_at is not None or self.dead_lettered_at is not None
