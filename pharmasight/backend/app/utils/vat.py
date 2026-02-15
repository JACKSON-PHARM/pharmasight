"""
VAT rate normalization for Kenyan system.

The database/Excel may store vat_rate as either:
- Percentage: 16 (meaning 16%)
- Decimal: 0.16 (meaning 16% but stored as decimal)

All calculations and API responses use percentage (0 or 16).
This module normalizes so 0.16 -> 16 and 16 -> 16.
"""

from decimal import Decimal
from typing import Union


def vat_rate_to_percent(value: Union[None, int, float, Decimal]) -> float:
    """
    Normalize vat_rate to percentage for display and calculation.

    - 0 or None -> 0
    - 0.16 (decimal) -> 16
    - 16 (percentage) -> 16
    - Values in (0, 1] are treated as decimal (e.g. 0.16 -> 16).
    """
    if value is None:
        return 0.0
    v = float(value)
    if v == 0:
        return 0.0
    if 0 < v <= 1:
        return v * 100
    return v
