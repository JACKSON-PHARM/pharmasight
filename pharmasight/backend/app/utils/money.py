from decimal import Decimal, ROUND_HALF_UP

MONEY_QUANT = Decimal("0.01")


def decimal_amount(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def money_amount(value) -> Decimal:
    """Round stored high-precision amounts to payable currency precision."""
    return decimal_amount(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
