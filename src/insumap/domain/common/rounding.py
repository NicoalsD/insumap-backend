"""Rounding the way the doctor reads it: half up, with ``Decimal``."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def round_half_up(value: Decimal, places: int) -> Decimal:
    """Round ``value`` to ``places`` decimals, ``.5`` going up (not banker's)."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
