"""TIR, TBR, TAR, GMI, CV, SMBG metrics and hypoglycemia episodes."""

import statistics
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from insumap.domain.metrics.glycemic_metrics import (
    Confidence,
    GlycemicMetrics,
    GlycemicMetricsCalculator,
    HypoglycemiaEpisode,
    Signal,
    detect_hypoglycemia_episodes,
    detect_signal,
    weigh,
)
from insumap.domain.metrics.target_profile import TargetProfile
from insumap.domain.metrics.window import GlucosePoint, GlucoseWindow
from insumap.domain.metrics.window_iterator import GlucoseWindowIterator, WindowSpec
from insumap.domain.monitoring.glucose import ReadingContext, ReadingSource
from tests.support.metrics_factories import PROFILE, series

BOGOTA = ZoneInfo("America/Bogota")
START = datetime(2026, 11, 10, 0, 0, tzinfo=BOGOTA)


def compute(
    points: list[GlucosePoint],
    days: int = 1,
    profile: TargetProfile = PROFILE,
    *,
    end: datetime | None = None,
) -> GlycemicMetrics:
    end = end or START + timedelta(days=days)
    window = GlucoseWindowIterator.window(points, START, end, min_points=1)
    spec = WindowSpec.daily(
        zone=BOGOTA, first_day=START.date(), days=days, min_points=1
    )
    return GlycemicMetricsCalculator(profile).compute(
        window, list(GlucoseWindowIterator(points, spec))
    )


def need(value: Decimal | None) -> Decimal:
    assert value is not None
    return value


def one_day(values: list[int]) -> GlycemicMetrics:
    """One local day sampled so that ``values`` fill the whole day evenly."""
    interval = 24 * 60 // len(values)
    return compute(series(START, values, interval_min=interval))


def test_the_five_bands_cover_the_time_and_add_up_to_100() -> None:
    # 288 readings, a fifth of the day in each band of the test profile.
    values = [40] * 58 + [60] * 58 + [120] * 58 + [200] * 57 + [300] * 57

    metrics = one_day(values)

    bands = [
        metrics.tbr_l2_pct,
        metrics.tbr_l1_pct,
        metrics.tir_pct,
        metrics.tar_l1_pct,
        metrics.tar_l2_pct,
    ]
    assert all(band is not None for band in bands)
    total = sum((need(band) for band in bands), Decimal(0))
    assert abs(total - 100) <= Decimal("0.05")
    assert metrics.tbr_pct == need(metrics.tbr_l1_pct) + need(metrics.tbr_l2_pct)
    assert metrics.tar_pct == need(metrics.tar_l1_pct) + need(metrics.tar_l2_pct)
    assert metrics.tir_pct == Decimal("20.14")


def test_the_limits_belong_to_the_band_the_profile_says() -> None:
    low, high = PROFILE.range_low_mg_dl, PROFILE.range_high_mg_dl
    very_low, very_high = PROFILE.very_low_mg_dl, PROFILE.very_high_mg_dl
    # range limits are in range; very low belongs to level 1; very high to level 1.
    edges = [int(low), int(high), int(very_low), int(very_high)] * 72

    metrics = one_day(edges)

    assert metrics.tir_pct == Decimal("50.00")
    assert metrics.tbr_l1_pct == Decimal("25.00")
    assert metrics.tbr_l2_pct == Decimal("0.00")
    assert metrics.tar_l1_pct == Decimal("25.00")
    assert metrics.tar_l2_pct == Decimal("0.00")


def test_the_gmi_of_a_mean_of_154_is_7_0() -> None:
    metrics = one_day([154] * 288)

    assert metrics.mean_glucose_mg_dl == Decimal("154.0")
    assert metrics.gmi_pct == Decimal("6.99")
    assert round(metrics.gmi_pct, 1) == Decimal("7.0")


def test_the_cv_of_a_known_series() -> None:
    metrics = one_day([100, 140] * 144)

    expected = statistics.stdev([100, 140] * 144) / 120 * 100
    assert metrics.cv_pct is not None
    assert abs(float(metrics.cv_pct) - expected) < 0.01
    assert metrics.mean_glucose_mg_dl == Decimal("120.0")


def test_the_cv_needs_the_minimum_of_readings_of_the_profile() -> None:
    few = replace(PROFILE, min_readings_for_cv=500)

    metrics = compute(series(START, [100, 140] * 144, interval_min=5), profile=few)

    assert metrics.cv_pct is None


def test_sufficiency_is_the_share_of_time_with_data_against_the_profile() -> None:
    def metrics_for(count: int) -> GlycemicMetrics:
        points = series(START, [100] * count, interval_min=1)
        return compute(points, end=START + timedelta(minutes=100))

    just_under = metrics_for(69)
    exact = metrics_for(70)

    assert PROFILE.min_data_sufficiency_pct == Decimal(70)
    assert just_under.data_sufficiency_pct == Decimal("69.0")
    assert not just_under.is_sufficient
    assert just_under.confidence is Confidence.LOW_CONFIDENCE
    assert exact.data_sufficiency_pct == Decimal("70.0")
    assert exact.is_sufficient
    assert exact.confidence is Confidence.NORMAL


def test_the_metrics_are_still_computed_when_the_data_is_insufficient() -> None:
    metrics = compute(series(START, [100] * 10, interval_min=5))

    assert not metrics.is_sufficient
    assert metrics.tir_pct == Decimal("100.00")


def test_gaps_longer_than_the_limit_count_as_holes_not_as_time() -> None:
    gap = PROFILE.max_gap_minutes
    first = series(START, [100], interval_min=5)
    later = series(START + timedelta(minutes=gap + 100), [300], interval_min=5)

    metrics = compute(first + later)

    # The first reading weighs the capped gap, the second the typical interval.
    assert metrics.tir_pct is not None
    assert Decimal(0) < metrics.tir_pct < Decimal(100)
    assert metrics.tir_pct == Decimal(gap) * 100 / (gap + gap)


def test_no_readings_gives_zero_sufficiency_and_no_values() -> None:
    metrics = compute([])

    assert metrics.data_sufficiency_pct == 0
    assert metrics.tir_pct is None
    assert metrics.confidence is Confidence.LOW_CONFIDENCE


def test_a_series_of_fingersticks_uses_glucometry_metrics() -> None:
    readings = []
    for day in range(10):
        base = START + timedelta(days=day)
        readings += series(
            base + timedelta(hours=7),
            [110],
            source=ReadingSource.SMBG,
            context=ReadingContext.FASTING,
        )
        readings += series(
            base + timedelta(hours=14),
            [200 if day % 2 else 150],
            source=ReadingSource.SMBG,
            context=ReadingContext.POST_MEAL,
        )

    metrics = compute(readings, days=10)

    assert detect_signal(readings) is Signal.SMBG
    assert metrics.signal is Signal.SMBG
    assert metrics.tir_pct is None
    assert metrics.gmi_pct is None
    assert metrics.readings_per_day == Decimal("2.0")
    assert metrics.days_with_data_pct == Decimal("100.0")
    assert metrics.fasting_median_mg_dl == Decimal("110.0")
    assert metrics.postprandial_median_mg_dl == Decimal("175.0")
    assert metrics.readings_in_range_pct == Decimal("75.0")
    assert metrics.readings_below_range_pct == Decimal("0.0")
    assert metrics.is_sufficient
    assert metrics.cv_pct is None  # 20 readings, the profile asks for 30


def test_smbg_sufficiency_counts_days_with_a_reading() -> None:
    readings = series(START, [100], source=ReadingSource.SMBG)

    metrics = compute(readings, days=10)

    assert metrics.days_with_data_pct == Decimal("10.0")
    assert not metrics.is_sufficient


def test_smbg_cv_appears_with_enough_readings() -> None:
    readings = []
    for index in range(40):
        readings += series(
            START + timedelta(hours=index),
            [100 if index % 2 else 140],
            source=ReadingSource.SMBG,
        )

    metrics = compute(readings, days=2)

    assert metrics.cv_pct is not None


def test_the_signal_is_cgm_only_when_most_readings_come_from_the_sensor() -> None:
    cgm = series(START, [100] * 3)
    smbg = series(START, [100] * 3, source=ReadingSource.SMBG)

    assert detect_signal(cgm + smbg) is Signal.SMBG
    assert detect_signal(cgm + smbg[:2]) is Signal.CGM


def episodes(values: list[int], start: datetime = START) -> list[HypoglycemiaEpisode]:
    points = series(start, values, interval_min=5)
    end = start + timedelta(minutes=5 * len(values))
    weighted = weigh(points, window_end=end, max_gap_minutes=PROFILE.max_gap_minutes)
    return detect_hypoglycemia_episodes(weighted, PROFILE)


def test_an_episode_needs_the_minimum_minutes_under_the_limit() -> None:
    assert episodes([100] * 6 + [65] * 2 + [100] * 6) == []
    found = episodes([100] * 6 + [65] * 3 + [100] * 6)

    assert len(found) == 1
    assert not found[0].level_2


def test_a_dip_under_the_very_low_limit_is_a_level_2_episode() -> None:
    found = episodes([100] * 6 + [50] * 3 + [100] * 6)

    assert len(found) == 1
    assert found[0].level_2


def test_a_level_1_episode_that_goes_lower_counts_once_as_level_2() -> None:
    found = episodes([100] * 6 + [65] * 2 + [50] * 3 + [100] * 6)

    assert len(found) == 1
    assert found[0].level_2


def test_a_short_recovery_does_not_end_the_episode() -> None:
    merged = episodes([65] * 3 + [100] * 2 + [65] * 3 + [100] * 6)
    split = episodes([65] * 3 + [100] * 3 + [65] * 3 + [100] * 6)

    assert len(merged) == 1
    assert len(split) == 2


def test_night_episodes_are_counted_by_local_time() -> None:
    night = START + timedelta(hours=3)
    afternoon = START + timedelta(hours=15)
    values = [100] * 288
    values[36:39] = [60] * 3  # 03:00 local
    values[180:183] = [60] * 3  # 15:00 local
    assert night < afternoon

    metrics = compute(series(START, values, interval_min=5))

    assert metrics.hypo_events_count == 2
    assert metrics.hypo_events_night_count == 1


def test_a_hole_in_the_data_closes_an_open_episode() -> None:
    before = series(START, [65] * 3, interval_min=5)
    after = series(START + timedelta(hours=3), [65] * 3, interval_min=5)
    weighted = weigh(
        before + after,
        window_end=START + timedelta(hours=4),
        max_gap_minutes=PROFILE.max_gap_minutes,
    )

    assert len(detect_hypoglycemia_episodes(weighted, PROFILE)) == 2


def test_weights_follow_the_time_each_reading_represents() -> None:
    points = series(START, [100, 100, 100], interval_min=5)

    weighted = weigh(points, window_end=START + timedelta(hours=1), max_gap_minutes=20)

    assert [w.minutes for w in weighted] == [Decimal(5), Decimal(5), Decimal(5)]


def test_the_last_reading_is_cut_at_the_end_of_the_window() -> None:
    points = series(START, [100, 100], interval_min=5)

    weighted = weigh(
        points, window_end=START + timedelta(minutes=7), max_gap_minutes=20
    )

    assert weighted[-1].minutes == Decimal(2)


def test_the_window_type_is_a_plain_container() -> None:
    window = GlucoseWindow(
        start=START, end=START + timedelta(days=1), points=(), has_enough_data=False
    )

    assert window.points == ()
    assert time(0, 0) == PROFILE.night_start
    assert date(2026, 11, 10) == START.date()
    assert START.astimezone(UTC).hour == 5
