"""The rule-based forecast of the backend (IA1 fallback, Modulo-IA 6.1).

It extrapolates the slope of the last 30 minutes. The band is the historical
dispersion of the series, so its width does not depend on the model. The
probabilities of crossing the thresholds come from a normal approximation: they
are an estimate, not a calibrated probability. Pure: the caller passes the
points and the thresholds, so the result depends only on its input.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from statistics import pstdev
from typing import Final, final

from insumap.domain.metrics.window import GlucosePoint

FALLBACK_MODEL_NAME: Final = "fallback-linear"
FALLBACK_MODEL_VERSION: Final = "fallback-linear@1.0.0"
SLOPE_WINDOW: Final = timedelta(minutes=30)
"""The recent change is measured over this window (Contrato-IA 8.1)."""
MIN_SLOPE_POINTS: Final = 2
"""A slope needs two readings inside the window."""
TREND_SLOPE_MG_DL_PER_MIN: Final = Decimal("1")
"""Technical threshold of the trend label, not a clinical target (Modulo-IA 6.1)."""
Z_P90: Final = 1.2816
"""Normal quantile of 0.9: the p10 to p90 band is ``p50 +/- Z_P90 * sigma``."""
MG_DL_STEP: Final = Decimal("0.1")
PROBABILITY_STEP: Final = Decimal("0.01")
DECIMAL_COMMA: Final = ","


class Trend(StrEnum):
    FALLING = "FALLING"
    STABLE = "STABLE"
    RISING = "RISING"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class LinearPoint:
    horizon_minutes: int
    timestamp: datetime
    p10: Decimal
    p50: Decimal
    p90: Decimal
    hypo_probability: Decimal
    hyper_probability: Decimal


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class LinearForecastResult:
    trend: Trend
    slope_mg_dl_per_min: Decimal
    last_mg_dl: Decimal
    points: tuple[LinearPoint, ...]
    summary: str


def linear_forecast(
    series: Sequence[GlucosePoint],
    *,
    horizons_minutes: Sequence[int],
    low_mg_dl: Decimal,
    high_mg_dl: Decimal,
) -> LinearForecastResult | None:
    """The forecast from ``series`` (oldest first), or ``None`` without enough data."""
    if len(series) < MIN_SLOPE_POINTS:
        return None
    last = series[-1]
    recent = [point for point in series if point.at >= last.at - SLOPE_WINDOW]
    if len(recent) < MIN_SLOPE_POINTS:
        return None
    slope = _slope(recent)
    if slope is None:
        return None
    sigma = pstdev([float(point.mg_dl) for point in series])
    last_value = float(last.mg_dl)
    points = tuple(
        _point(
            horizon=horizon,
            origin=last.at,
            p50=last_value + slope * horizon,
            sigma=sigma,
            low=float(low_mg_dl),
            high=float(high_mg_dl),
        )
        for horizon in horizons_minutes
    )
    trend = _trend(slope)
    last_decimal = _mg_dl(last_value)
    slope_decimal = _mg_dl(slope, step=Decimal("0.01"))
    return LinearForecastResult(
        trend=trend,
        slope_mg_dl_per_min=slope_decimal,
        last_mg_dl=last_decimal,
        points=points,
        summary=_summary(last_decimal, slope_decimal, trend),
    )


def _slope(points: Sequence[GlucosePoint]) -> float | None:
    """Least squares slope in mg/dL per minute, or ``None`` if time does not move."""
    origin = points[0].at
    xs = [(point.at - origin).total_seconds() / 60 for point in points]
    ys = [float(point.mg_dl) for point in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return covariance / variance


def _point(
    *, horizon: int, origin: datetime, p50: float, sigma: float, low: float, high: float
) -> LinearPoint:
    spread = Z_P90 * sigma
    return LinearPoint(
        horizon_minutes=horizon,
        timestamp=origin + timedelta(minutes=horizon),
        p10=_mg_dl(p50 - spread),
        p50=_mg_dl(p50),
        p90=_mg_dl(p50 + spread),
        hypo_probability=_probability(p50, sigma, below=low),
        hyper_probability=_probability(p50, sigma, above=high),
    )


def _probability(
    center: float,
    sigma: float,
    *,
    below: float | None = None,
    above: float | None = None,
) -> Decimal:
    """Chance of crossing a threshold under a normal of mean ``center``."""
    if sigma == 0:
        crosses = (below is not None and center < below) or (
            above is not None and center > above
        )
        return Decimal("1") if crosses else Decimal("0")
    if below is not None:
        value = _normal_cdf((below - center) / sigma)
    else:
        value = 1 - _normal_cdf(((above or 0.0) - center) / sigma)
    return _round(Decimal(repr(min(max(value, 0.0), 1.0))), PROBABILITY_STEP)


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _trend(slope: float) -> Trend:
    threshold = float(TREND_SLOPE_MG_DL_PER_MIN)
    if slope < -threshold:
        return Trend.FALLING
    if slope > threshold:
        return Trend.RISING
    return Trend.STABLE


def _summary(last: Decimal, slope: Decimal, trend: Trend) -> str:
    rate = f"{slope:+.1f}".replace(".", DECIMAL_COMMA)
    return (
        f"Respaldo por reglas: glucosa de {last:.0f} mg/dL con tendencia "
        f"{trend.value.lower()} de {rate} mg/dL por minuto."
    )


def _mg_dl(value: float, *, step: Decimal = MG_DL_STEP) -> Decimal:
    return _round(Decimal(repr(value)), step)


def _round(value: Decimal, step: Decimal) -> Decimal:
    return value.quantize(step, rounding=ROUND_HALF_UP)
