"""Privacy rule of the clinic indicators: small groups are not shown (RF-83).

A count between one and the threshold could single out a patient, so it is
hidden. Zero is not identifying and stays visible.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

HUNDRED: Final = Decimal("100")
PERCENT_QUANTUM: Final = Decimal("0.01")


def is_too_small(count: int, threshold: int) -> bool:
    """True when the count is positive but below the threshold."""
    return 0 < count < threshold


def percentage(part: int, whole: int, threshold: int) -> Decimal | None:
    """``part`` over ``whole`` as a percentage with two decimals.

    ``None`` when the group is empty or smaller than the threshold: a rate over
    a handful of patients identifies them as well.
    """
    if whole == 0 or whole < threshold:
        return None
    return (Decimal(part) * HUNDRED / Decimal(whole)).quantize(
        PERCENT_QUANTUM, rounding=ROUND_HALF_UP
    )
