from decimal import Decimal


MAX_PROCESSING_FAILURES = 3

MIN_PAYMENT_AMOUNT = Decimal("0")  # The amount must be strictly greater than zero.
MAX_PAYMENT_AMOUNT = Decimal("9999999999999999.99")
PAYMENT_AMOUNT_PRECISION = 18
PAYMENT_AMOUNT_SCALE = 2
PAYMENT_AMOUNT_QUANTUM = Decimal("0.01")
