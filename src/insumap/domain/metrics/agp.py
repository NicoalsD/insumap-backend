"""Ambulatory glucose profile: percentiles of the day of the patient by time bin."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Final, final
from zoneinfo import ZoneInfo

from insumap.domain.common.rounding import round_half_up
from insumap.domain.metrics.window import GlucosePoint
from insumap.shared.units import MINUTES_PER_DAY

AGP_PERCENTILES: Final = (5, 25, 50, 75, 95)
"""The standard AGP presentation: a view setting, not a clinical target."""
PERCENTILE_DECIMALS = 1
HUNDRED = Decimal(100)


class AgpResolution(Enum):
    """Width of a bin in minutes: one hour, or a fine 15 minute view."""

    HOUR = 60
    QUARTER = 15


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AgpBin:
    """Percentiles of every reading that fell in one time of day bin."""

    minute_of_day: int
    p5: Decimal
    p25: Decimal
    p50: Decimal
    p75: Decimal
    p95: Decimal


def percentile(sorted_values: Sequence[Decimal], pct: int) -> Decimal:
    """Linear interpolation between ranks (the default of ``numpy.percentile``)."""
    if not sorted_values:
        raise ValueError("percentile of an empty series")
    rank = Decimal(len(sorted_values) - 1) * Decimal(pct) / HUNDRED
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (
        fraction
    )


def compute_agp(
    points: Sequence[GlucosePoint], zone: ZoneInfo, resolution: AgpResolution
) -> tuple[AgpBin, ...]:
    """Superimpose the days of ``points`` on a 24 hour axis of the clinic zone.

    The raw percentiles are returned; smoothing, if any, is only for drawing.
    """
    width = resolution.value
    by_bin: dict[int, list[Decimal]] = {}
    for point in points:
        local = point.at.astimezone(zone)
        minute = local.hour * 60 + local.minute
        by_bin.setdefault(minute // width, []).append(point.mg_dl)
    bins: list[AgpBin] = []
    for index in range(MINUTES_PER_DAY // width):
        values = sorted(by_bin.get(index, ()))
        if not values:
            continue
        p5, p25, p50, p75, p95 = (
            round_half_up(percentile(values, pct), PERCENTILE_DECIMALS)
            for pct in AGP_PERCENTILES
        )
        bins.append(
            AgpBin(
                minute_of_day=index * width,
                p5=p5,
                p25=p25,
                p50=p50,
                p75=p75,
                p95=p95,
            )
        )
    return tuple(bins)
