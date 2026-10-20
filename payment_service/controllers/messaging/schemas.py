from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PaymentNew(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: UUID
