"""Windows over a glucose series: local days, nights and multi day periods (P14)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import final
from zoneinfo import ZoneInfo

from insumap.domain.metrics.window import GlucosePoint, GlucoseWindow

MIDNIGHT = time(0, 0)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class WindowSpec:
    """Where and how to cut windows, always in the zone of the clinic.

    ``count`` windows start on consecutive days from ``first_day``. A window runs
    from ``starts_at`` of its day to ``ends_at``: the same time of the day after
    ``span_days`` days (a day, or 14 days), or ``ends_at`` of the same day when it
    is later than ``starts_at`` (``00:00`` to ``06:00``), or of the next day when
    it is not (``22:00`` to ``06:00``). Night limits and ``min_points`` come from
    the target profile.
    """

    zone: ZoneInfo
    first_day: date
    count: int
    starts_at: time
    ends_at: time
    min_points: int
    span_days: int = 1

    @classmethod
    def daily(
        cls, *, zone: ZoneInfo, first_day: date, days: int, min_points: int
    ) -> WindowSpec:
        """``days`` local days, ``[00:00, 24:00)`` each."""
        return cls(
            zone=zone,
            first_day=first_day,
            count=days,
            starts_at=MIDNIGHT,
            ends_at=MIDNIGHT,
            min_points=min_points,
        )

    @classmethod
    def nocturnal(
        cls,
        *,
        zone: ZoneInfo,
        first_day: date,
        days: int,
        night_start: time,
        night_end: time,
        min_points: int,
    ) -> WindowSpec:
        """The night of each of ``days`` local days."""
        return cls(
            zone=zone,
            first_day=first_day,
            count=days,
            starts_at=night_start,
            ends_at=night_end,
            min_points=min_points,
        )

    @classmethod
    def period(
        cls, *, zone: ZoneInfo, first_day: date, span_days: int, min_points: int
    ) -> WindowSpec:
        """One window of ``span_days`` local days (the 14 day reference period)."""
        return cls(
            zone=zone,
            first_day=first_day,
            count=1,
            starts_at=MIDNIGHT,
            ends_at=MIDNIGHT,
            min_points=min_points,
            span_days=span_days,
        )


@final
class GlucoseWindowIterator:
    """Iterates local day, night or period windows over a series of readings.

    Boundaries are wall clock times of the clinic zone, so a day with a daylight
    saving change has 23 or 25 hours and a reading near midnight UTC falls in
    the right local day. The readings are sorted first, so the order they
    arrive in does not matter.

    Pattern: P14 Iterator
    """

    def __init__(self, points: Sequence[GlucosePoint], spec: WindowSpec) -> None:
        self._points = tuple(sorted(points, key=lambda point: point.at))
        self._spec = spec

    def __iter__(self) -> Iterator[GlucoseWindow]:
        spec = self._spec
        for offset in range(spec.count):
            day = spec.first_day + timedelta(days=offset)
            end_day = (
                day
                if spec.ends_at > spec.starts_at
                else day + timedelta(days=spec.span_days)
            )
            yield self.window(
                self._points,
                datetime.combine(day, spec.starts_at, tzinfo=spec.zone),
                datetime.combine(end_day, spec.ends_at, tzinfo=spec.zone),
                min_points=spec.min_points,
            )

    @staticmethod
    def window(
        points: Sequence[GlucosePoint],
        start: datetime,
        end: datetime,
        *,
        min_points: int,
    ) -> GlucoseWindow:
        """The points of ``points`` in ``[start, end)``, for any pair of instants."""
        # Compared in UTC: two datetimes of the same zone would be compared as
        # wall clock times, which is wrong in the repeated hour of a clock change.
        first, last = start.astimezone(UTC), end.astimezone(UTC)
        inside = tuple(p for p in points if first <= p.at.astimezone(UTC) < last)
        return GlucoseWindow(
            start=start,
            end=end,
            points=inside,
            has_enough_data=len(inside) >= min_points,
        )
