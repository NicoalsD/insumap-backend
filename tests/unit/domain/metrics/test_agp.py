"""AGP percentiles: interpolation, bins by local time and resolutions."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from insumap.domain.metrics.agp import AgpResolution, compute_agp, percentile
from insumap.domain.metrics.window import GlucosePoint

BOGOTA = ZoneInfo("America/Bogota")


def values(*numbers: str) -> list[Decimal]:
    return [Decimal(n) for n in numbers]


def test_percentiles_interpolate_linearly_like_numpy() -> None:
    data = values("1", "2", "3", "4", "5")

    assert percentile(data, 50) == Decimal(3)
    assert percentile(data, 25) == Decimal(2)
    assert percentile(data, 75) == Decimal(4)
    assert percentile(data, 5) == Decimal("1.2")
    assert percentile(data, 95) == Decimal("4.8")


def test_percentile_of_one_value_and_of_an_even_count() -> None:
    assert percentile(values("7"), 95) == Decimal(7)
    assert percentile(values("10", "20", "30", "40"), 50) == Decimal(25)
    assert percentile(values("10", "20", "30", "40"), 75) == Decimal("32.5")


def test_percentile_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError, match="empty"):
        percentile([], 50)


def at(hour: int, minute: int, day: int, value: int) -> GlucosePoint:
    return GlucosePoint(
        at=datetime(2026, 11, day, hour, minute, tzinfo=BOGOTA), mg_dl=Decimal(value)
    )


def test_days_are_superimposed_on_a_local_24_hour_axis() -> None:
    points = [
        at(8, 5, 10, 100),
        at(8, 30, 11, 120),
        at(8, 55, 12, 140),
        at(9, 0, 10, 200),
    ]

    bins = compute_agp(points, BOGOTA, AgpResolution.HOUR)

    assert [b.minute_of_day for b in bins] == [8 * 60, 9 * 60]
    assert (bins[0].p5, bins[0].p50, bins[0].p95) == (
        Decimal("102.0"),
        Decimal("120.0"),
        Decimal("138.0"),
    )
    assert bins[1].p50 == Decimal("200.0")


def test_the_fine_resolution_uses_quarter_hour_bins() -> None:
    points = [at(8, 5, 10, 100), at(8, 20, 10, 110), at(8, 59, 10, 120)]

    bins = compute_agp(points, BOGOTA, AgpResolution.QUARTER)

    assert [b.minute_of_day for b in bins] == [8 * 60, 8 * 60 + 15, 8 * 60 + 45]


def test_a_reading_in_utc_is_binned_by_the_clinic_clock() -> None:
    utc_reading = GlucosePoint(
        at=datetime(2026, 11, 19, 3, 10, tzinfo=UTC), mg_dl=Decimal(100)
    )

    [bin_] = compute_agp([utc_reading], BOGOTA, AgpResolution.HOUR)

    assert bin_.minute_of_day == 22 * 60


def test_no_readings_means_no_bins() -> None:
    assert compute_agp([], BOGOTA, AgpResolution.HOUR) == ()
