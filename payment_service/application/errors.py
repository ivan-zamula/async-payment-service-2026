"""Errors raised by application scenarios."""


class PaymentNotFoundError(Exception):
    """The requested payment does not exist."""
