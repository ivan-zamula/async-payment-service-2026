"""Payment amount limits shared by domain validation, API schemas and storage."""

from decimal import Decimal


MIN_PAYMENT_AMOUNT = Decimal("0")  # Exclusive lower bound.
MAX_PAYMENT_AMOUNT = Decimal("9999999999999999.99")
PAYMENT_AMOUNT_PRECISION = 18
PAYMENT_AMOUNT_SCALE = 2
PAYMENT_AMOUNT_QUANTUM = Decimal("0.01")
