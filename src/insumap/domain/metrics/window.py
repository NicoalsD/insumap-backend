"""The glucose points and windows the metrics are computed over."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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


def elapsed_minutes(start: datetime, end: datetime) -> Decimal:
    """Real minutes between two instants.

    Subtracting two datetimes with the same ``tzinfo`` ignores daylight saving,
    so both are taken to UTC first: a local day can last 23 or 25 hours.
    """
    seconds = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()
    return Decimal(str(seconds)) / SECONDS_PER_MINUTE


SECONDS_PER_MINUTE = Decimal(60)
