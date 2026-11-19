"""The glucose points and windows the metrics are computed over."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from insumap.domain.monitoring.glucose import ReadingContext, ReadingSource


@dataclass(frozen=True, slots=True, kw_only=True)
class GlucosePoint:
    """One valid reading of the series, in mg/dL."""

    at: datetime
    mg_dl: Decimal
    source: ReadingSource = ReadingSource.CGM
    context: ReadingContext | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseWindow:
    """The points that fall in ``[start, end)`` and whether there are enough."""

    start: datetime
    end: datetime
    points: tuple[GlucosePoint, ...]
    has_enough_data: bool
