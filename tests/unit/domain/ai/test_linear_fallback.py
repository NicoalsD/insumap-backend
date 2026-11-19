from datetime import UTC, datetime, timedelta
from decimal import Decimal

from insumap.domain.ai.linear_fallback import (
    FALLBACK_MODEL_VERSION,
    Trend,
    linear_forecast,
)
from insumap.domain.metrics.window import GlucosePoint

START = datetime(2026, 11, 19, 21, 0, tzinfo=UTC)
LOW = Decimal("70")
HIGH = Decimal("180")


def series(values: list[float], *, step_minutes: int = 5) -> list[GlucosePoint]:
    return [
        GlucosePoint(
            at=START + timedelta(minutes=step_minutes * index),
            mg_dl=Decimal(str(value)),
        )
        for index, value in enumerate(values)
    ]


def test_too_few_readings_give_no_forecast() -> None:
    assert (
        linear_forecast(
            series([100.0]), horizons_minutes=[30], low_mg_dl=LOW, high_mg_dl=HIGH
        )
        is None
    )


def test_a_falling_series_extrapolates_its_slope() -> None:
    result = linear_forecast(
        series([128.0, 121.0, 113.0, 108.0]),
        horizons_minutes=[30, 60],
        low_mg_dl=LOW,
        high_mg_dl=HIGH,
    )

    assert result is not None
    assert result.trend is Trend.FALLING
    assert result.last_mg_dl == Decimal("108.0")
    assert result.slope_mg_dl_per_min < 0
    first, second = result.points
    assert first.horizon_minutes == 30
    assert first.p50 < result.last_mg_dl
    assert second.p50 < first.p50
    assert first.timestamp == START + timedelta(minutes=15 + 30)


def test_a_flat_series_is_stable_and_has_a_zero_band() -> None:
    result = linear_forecast(
        series([100.0, 100.0, 100.0]),
        horizons_minutes=[30],
        low_mg_dl=LOW,
        high_mg_dl=HIGH,
    )

    assert result is not None
    assert result.trend is Trend.STABLE
    (point,) = result.points
    assert point.p10 == point.p50 == point.p90 == Decimal("100.0")
    assert point.hypo_probability == Decimal("0")
    assert point.hyper_probability == Decimal("0")


def test_the_band_is_ordered_and_crossing_a_threshold_raises_its_probability() -> None:
    result = linear_forecast(
        series([95.0, 90.0, 80.0, 72.0, 80.0, 75.0, 60.0, 90.0, 110.0, 85.0]),
        horizons_minutes=[30, 120],
        low_mg_dl=LOW,
        high_mg_dl=HIGH,
    )

    assert result is not None
    for point in result.points:
        assert point.p10 <= point.p50 <= point.p90
        assert Decimal("0") <= point.hypo_probability <= Decimal("1")
        assert Decimal("0") <= point.hyper_probability <= Decimal("1")
    near, far = result.points
    assert far.hypo_probability >= near.hypo_probability
    assert near.hyper_probability == Decimal("0.00")


def test_a_rising_series_is_labelled_rising() -> None:
    result = linear_forecast(
        series([100.0, 115.0, 130.0, 150.0]),
        horizons_minutes=[30],
        low_mg_dl=LOW,
        high_mg_dl=HIGH,
    )

    assert result is not None
    assert result.trend is Trend.RISING
    assert result.points[0].hyper_probability > Decimal("0")


def test_the_summary_is_spanish_and_has_no_dose() -> None:
    result = linear_forecast(
        series([128.0, 121.0, 113.0, 108.0]),
        horizons_minutes=[30],
        low_mg_dl=LOW,
        high_mg_dl=HIGH,
    )

    assert result is not None
    assert result.summary.startswith("Respaldo por reglas")
    assert "," in result.summary
    assert "unidad" not in result.summary
    assert FALLBACK_MODEL_VERSION == "fallback-linear@1.0.0"


def test_readings_at_the_same_instant_give_no_slope() -> None:
    same = [
        GlucosePoint(at=START, mg_dl=Decimal("100")),
        GlucosePoint(at=START, mg_dl=Decimal("120")),
    ]

    assert (
        linear_forecast(same, horizons_minutes=[30], low_mg_dl=LOW, high_mg_dl=HIGH)
        is None
    )
