"""Errors raised by application scenarios."""


class PaymentNotFoundError(Exception):
    """The requested payment does not exist."""


class IdempotencyConflictError(Exception):
    """An idempotency key was reused with different payment data."""
