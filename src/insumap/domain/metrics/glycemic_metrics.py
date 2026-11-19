"""The glycemic metrics of a period: TIR, TBR, TAR, mean, GMI, CV and episodes.

Formulas and sources are in ``docs/Metricas-clinicas.md``. Every threshold is
read from the target profile (a database row); the only literals here are the
published GMI and unit constants of ``insumap.shared.units``.
"""

from __future__ import annotations

import itertools
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import final

from insumap.domain.common.rounding import round_half_up
from insumap.domain.metrics.target_profile import TargetProfile
from insumap.domain.metrics.window import GlucosePoint, GlucoseWindow, elapsed_minutes
from insumap.domain.monitoring.glucose import ReadingContext, ReadingSource
from insumap.shared.units import GMI_INTERCEPT, GMI_SLOPE_PER_MG_DL, PERCENT

PERCENT_DECIMALS = 2
GLUCOSE_DECIMALS = 1
RATIO_DECIMALS = 1
ZERO = Decimal(0)


class Signal(StrEnum):
    """Which family of metrics applies: continuous sensor or fingerstick."""

    CGM = "CGM"
    SMBG = "SMBG"


class Confidence(StrEnum):
    NORMAL = "NORMAL"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class GlycemicMetrics:
    """The metrics of one period. ``None`` means the data does not allow it.

    Values are rounded half up to the precision the dictionary says is stored:
    two decimals for percentages, one for glucose and sufficiency.
    """

    signal: Signal
    data_sufficiency_pct: Decimal
    is_sufficient: bool
    confidence: Confidence
    mean_glucose_mg_dl: Decimal | None = None
    cv_pct: Decimal | None = None
    tir_pct: Decimal | None = None
    tbr_l1_pct: Decimal | None = None
    tbr_l2_pct: Decimal | None = None
    tbr_pct: Decimal | None = None
    tar_l1_pct: Decimal | None = None
    tar_l2_pct: Decimal | None = None
    tar_pct: Decimal | None = None
    gmi_pct: Decimal | None = None
    hypo_events_count: int | None = None
    hypo_events_night_count: int | None = None
    readings_per_day: Decimal | None = None
    days_with_data_pct: Decimal | None = None
    readings_in_range_pct: Decimal | None = None
    readings_below_range_pct: Decimal | None = None
    readings_below_very_low_pct: Decimal | None = None
    fasting_median_mg_dl: Decimal | None = None
    postprandial_median_mg_dl: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class _Weighted:
    """A reading and the minutes of time it represents."""

    point: GlucosePoint
    minutes: Decimal


def detect_signal(points: Sequence[GlucosePoint]) -> Signal:
    """CGM when most readings come from the sensor, glucometry otherwise."""
    sensor = sum(1 for point in points if point.source is ReadingSource.CGM)
    return Signal.CGM if sensor * 2 > len(points) else Signal.SMBG


def weigh(
    points: Sequence[GlucosePoint], *, window_end: datetime, max_gap_minutes: int
) -> list[_Weighted]:
    """Time each reading represents: until the next one, capped at the gap limit.

    A longer silence is a hole that counts for nothing. The last reading
    represents the typical interval of the series (never more than the cap or
    the end of the window), so regular sampling weighs every reading the same.
    """
    ordered = sorted(
        (replace(point, at=point.at.astimezone(UTC)) for point in points),
        key=lambda point: point.at,
    )
    cap = Decimal(max_gap_minutes)
    gaps = [
        min(elapsed_minutes(a.at, b.at), cap) for a, b in itertools.pairwise(ordered)
    ]
    typical = Decimal(str(statistics.median(gaps))) if gaps else ZERO
    weighted = [
        _Weighted(point=point, minutes=minutes)
        for point, minutes in zip(ordered, gaps, strict=False)
    ]
    if ordered:
        left = elapsed_minutes(ordered[-1].at, window_end)
        weighted.append(
            _Weighted(point=ordered[-1], minutes=max(ZERO, min(typical, left)))
        )
    return weighted


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    return part * PERCENT / whole


def _weighted_sd(values: Sequence[_Weighted], mean: Decimal) -> Decimal | None:
    """Sample standard deviation with time weights (reliability weights)."""
    total = sum((w.minutes for w in values), ZERO)
    squares = sum((w.minutes * w.minutes for w in values), ZERO)
    if total == 0:
        return None
    denominator = total - squares / total
    if denominator <= 0:
        return None
    variance = (
        sum((w.minutes * (w.point.mg_dl - mean) ** 2 for w in values), ZERO)
        / denominator
    )
    return variance.sqrt()


def _in_night(at: datetime, night_start: time, night_end: time) -> bool:
    local = at.timetz().replace(tzinfo=None)
    if night_end > night_start:
        return night_start <= local < night_end
    return local >= night_start or local < night_end


@final
class GlycemicMetricsCalculator:
    """Computes the metrics of a period with the thresholds of a target profile."""

    def __init__(self, profile: TargetProfile) -> None:
        self._profile = profile

    def compute(
        self, period: GlucoseWindow, days: Sequence[GlucoseWindow]
    ) -> GlycemicMetrics:
        """Metrics of ``period``; ``days`` are its local days (P14 windows)."""
        if not period.points:
            return self._empty(detect_signal(()))
        signal = detect_signal(period.points)
        if signal is Signal.CGM:
            return self._cgm(period)
        return self._smbg(period, days)

    def _empty(self, signal: Signal) -> GlycemicMetrics:
        return GlycemicMetrics(
            signal=signal,
            data_sufficiency_pct=ZERO,
            is_sufficient=False,
            confidence=Confidence.LOW_CONFIDENCE,
        )

    def _cgm(self, period: GlucoseWindow) -> GlycemicMetrics:
        profile = self._profile
        weighted = weigh(
            period.points,
            window_end=period.end,
            max_gap_minutes=profile.max_gap_minutes,
        )
        observed = sum((w.minutes for w in weighted), ZERO)
        total_minutes = elapsed_minutes(period.start, period.end)
        sufficiency = min(PERCENT, _pct(observed, total_minutes))
        sufficient = sufficiency >= profile.min_data_sufficiency_pct
        if observed == 0:
            return self._empty(Signal.CGM)

        def share(selected: Sequence[_Weighted]) -> Decimal:
            return _pct(sum((w.minutes for w in selected), ZERO), observed)

        very_low = [w for w in weighted if w.point.mg_dl < profile.very_low_mg_dl]
        low = [
            w
            for w in weighted
            if profile.very_low_mg_dl <= w.point.mg_dl < profile.range_low_mg_dl
        ]
        in_range = [
            w
            for w in weighted
            if profile.range_low_mg_dl <= w.point.mg_dl <= profile.range_high_mg_dl
        ]
        high = [
            w
            for w in weighted
            if profile.range_high_mg_dl < w.point.mg_dl <= profile.very_high_mg_dl
        ]
        very_high = [w for w in weighted if w.point.mg_dl > profile.very_high_mg_dl]
        mean = sum((w.minutes * w.point.mg_dl for w in weighted), ZERO) / observed
        sd = _weighted_sd(weighted, mean)
        enough_for_cv = len(period.points) >= profile.min_readings_for_cv
        episodes = detect_hypoglycemia_episodes(weighted, profile)
        gmi = GMI_INTERCEPT + GMI_SLOPE_PER_MG_DL * mean
        return GlycemicMetrics(
            signal=Signal.CGM,
            data_sufficiency_pct=round_half_up(sufficiency, GLUCOSE_DECIMALS),
            is_sufficient=sufficient,
            confidence=Confidence.NORMAL if sufficient else Confidence.LOW_CONFIDENCE,
            mean_glucose_mg_dl=round_half_up(mean, GLUCOSE_DECIMALS),
            cv_pct=(
                round_half_up(_pct(sd, mean), PERCENT_DECIMALS)
                if sd is not None and enough_for_cv and mean > 0
                else None
            ),
            tir_pct=round_half_up(share(in_range), PERCENT_DECIMALS),
            tbr_l1_pct=round_half_up(share(low), PERCENT_DECIMALS),
            tbr_l2_pct=round_half_up(share(very_low), PERCENT_DECIMALS),
            tbr_pct=round_half_up(share(low + very_low), PERCENT_DECIMALS),
            tar_l1_pct=round_half_up(share(high), PERCENT_DECIMALS),
            tar_l2_pct=round_half_up(share(very_high), PERCENT_DECIMALS),
            tar_pct=round_half_up(share(high + very_high), PERCENT_DECIMALS),
            gmi_pct=round_half_up(gmi, PERCENT_DECIMALS),
            hypo_events_count=len(episodes),
            hypo_events_night_count=sum(
                1
                for episode in episodes
                if _in_night(
                    episode.started_at.astimezone(period.start.tzinfo),
                    profile.night_start,
                    profile.night_end,
                )
            ),
        )

    def _smbg(
        self, period: GlucoseWindow, days: Sequence[GlucoseWindow]
    ) -> GlycemicMetrics:
        profile = self._profile
        values = [point.mg_dl for point in period.points]
        count = Decimal(len(values))
        days_with_data = sum(1 for day in days if day.points)
        total_days = Decimal(len(days)) if days else Decimal(1)
        coverage = _pct(Decimal(days_with_data), total_days)
        sufficient = coverage >= profile.min_data_sufficiency_pct
        mean = sum(values, ZERO) / count

        def share(selected: list[Decimal]) -> Decimal:
            return round_half_up(_pct(Decimal(len(selected)), count), RATIO_DECIMALS)

        fasting = [
            p.mg_dl for p in period.points if p.context is ReadingContext.FASTING
        ]
        post = [p.mg_dl for p in period.points if p.context is ReadingContext.POST_MEAL]
        cv = None
        if len(values) >= profile.min_readings_for_cv_smbg and mean > 0:
            sd = _plain_sd(values, mean)
            cv = None if sd is None else round_half_up(_pct(sd, mean), RATIO_DECIMALS)
        return GlycemicMetrics(
            signal=Signal.SMBG,
            data_sufficiency_pct=round_half_up(coverage, GLUCOSE_DECIMALS),
            is_sufficient=sufficient,
            confidence=Confidence.NORMAL if sufficient else Confidence.LOW_CONFIDENCE,
            mean_glucose_mg_dl=round_half_up(mean, GLUCOSE_DECIMALS),
            cv_pct=cv,
            readings_per_day=(
                round_half_up(count / Decimal(days_with_data), RATIO_DECIMALS)
                if days_with_data
                else None
            ),
            days_with_data_pct=round_half_up(coverage, RATIO_DECIMALS),
            readings_in_range_pct=share(
                [
                    v
                    for v in values
                    if profile.range_low_mg_dl <= v <= profile.range_high_mg_dl
                ]
            ),
            readings_below_range_pct=share(
                [v for v in values if v < profile.range_low_mg_dl]
            ),
            readings_below_very_low_pct=share(
                [v for v in values if v < profile.very_low_mg_dl]
            ),
            fasting_median_mg_dl=_median(fasting),
            postprandial_median_mg_dl=_median(post),
        )


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return round_half_up(Decimal(str(statistics.median(values))), GLUCOSE_DECIMALS)


def _plain_sd(values: Sequence[Decimal], mean: Decimal) -> Decimal | None:
    if len(values) < 2:  # noqa: PLR2004 - a sample SD needs two values
        return None
    variance = sum(((v - mean) ** 2 for v in values), ZERO) / Decimal(len(values) - 1)
    return variance.sqrt()


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class HypoglycemiaEpisode:
    """A stretch under the low limit that lasted long enough to count."""

    started_at: datetime
    level_2: bool


def detect_hypoglycemia_episodes(
    weighted: Sequence[_Weighted], profile: TargetProfile
) -> list[HypoglycemiaEpisode]:
    """Episodes of at least ``hypo_episode_min_minutes`` under the low limit.

    An episode ends when the glucose is back at or over the limit for the same
    number of minutes, or when a hole in the data breaks the series. One that
    also spent that long under the very low limit counts once, as level 2.
    """
    minimum = Decimal(profile.hypo_episode_min_minutes)
    episodes: list[HypoglycemiaEpisode] = []
    started: datetime | None = None
    below = recovery = very_low_run = very_low_best = ZERO

    def close() -> None:
        nonlocal started, below, recovery, very_low_run, very_low_best
        if started is not None and below >= minimum:
            episodes.append(
                HypoglycemiaEpisode(
                    started_at=started, level_2=very_low_best >= minimum
                )
            )
        started = None
        below = recovery = very_low_run = very_low_best = ZERO

    previous_end: datetime | None = None
    for item in weighted:
        point = item.point
        if previous_end is not None and point.at - previous_end > timedelta(0):
            close()  # a hole in the data
        previous_end = point.at + timedelta(minutes=float(item.minutes))
        if point.mg_dl < profile.range_low_mg_dl:
            if started is None:
                started = point.at
            below += item.minutes
            recovery = ZERO
            if point.mg_dl < profile.very_low_mg_dl:
                very_low_run += item.minutes
                very_low_best = max(very_low_best, very_low_run)
            else:
                very_low_run = ZERO
        elif started is not None:
            recovery += item.minutes
            very_low_run = ZERO
            if recovery >= minimum:
                close()
    close()
    return episodes
