"""Glucose series and a target profile declared by the tests."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from decimal import Decimal

from insumap.domain.metrics.window import GlucosePoint
from insumap.domain.monitoring.glucose import ReadingContext, ReadingSource
from tests.support.monitoring_fakes import TEST_PROFILE

PROFILE = TEST_PROFILE


def series(
    start: datetime,
    values: Iterable[int | str],
    *,
    interval_min: int = 5,
    source: ReadingSource = ReadingSource.CGM,
    context: ReadingContext | None = None,
) -> list[GlucosePoint]:
    """One reading per ``interval_min`` minutes with the given values."""
    return [
        GlucosePoint(
            at=start + timedelta(minutes=interval_min * index),
            mg_dl=Decimal(value),
            source=source,
            context=context,
        )
        for index, value in enumerate(values)
    ]


def repeating(pattern: list[int], times: int) -> list[int]:
    return pattern * times


def ramp(count: int, value: Callable[[int], int]) -> list[int]:
    return [value(index) for index in range(count)]
