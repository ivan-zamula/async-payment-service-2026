"""Events passed from the outbox repository to the message publisher."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: UUID
    event_type: str
    payload: dict[str, Any]
