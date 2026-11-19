"""P14 Iterator: local day, night and period windows in the clinic zone."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from insumap.domain.metrics.window import GlucosePoint, GlucoseWindow
from insumap.domain.metrics.window_iterator import GlucoseWindowIterator, WindowSpec

BOGOTA = ZoneInfo("America/Bogota")
NEW_YORK = ZoneInfo("America/New_York")
HOUR = timedelta(hours=1)


def point(at: datetime, value: int = 100) -> GlucosePoint:
    return GlucosePoint(at=at, mg_dl=Decimal(value))


def daily(zone: ZoneInfo, first: date, days: int, points: list[GlucosePoint]):  # type: ignore[no-untyped-def]
    spec = WindowSpec.daily(zone=zone, first_day=first, days=days, min_points=1)
    return list(GlucoseWindowIterator(points, spec))


def test_a_reading_at_03_utc_belongs_to_the_previous_local_day() -> None:
    reading = point(datetime(2026, 11, 19, 3, 0, tzinfo=UTC))  # 22:00 on the 18th

    windows = daily(BOGOTA, date(2026, 11, 18), 2, [reading])

    assert [len(w.points) for w in windows] == [1, 0]
    assert [w.has_enough_data for w in windows] == [True, False]


def test_a_day_that_crosses_midnight_utc_but_not_the_local_one_stays_whole() -> None:
    evening = point(datetime(2026, 11, 19, 1, 0, tzinfo=UTC))  # 20:00 on the 18th
    late = point(datetime(2026, 11, 19, 4, 59, tzinfo=UTC))  # 23:59 on the 18th
    next_day = point(datetime(2026, 11, 19, 5, 0, tzinfo=UTC))  # 00:00 on the 19th

    windows = daily(BOGOTA, date(2026, 11, 18), 2, [next_day, late, evening])

    assert [len(w.points) for w in windows] == [2, 1]


def test_the_night_window_uses_the_profile_limits_and_crosses_midnight() -> None:
    spec = WindowSpec.nocturnal(
        zone=BOGOTA,
        first_day=date(2026, 11, 18),
        days=1,
        night_start=time(22, 0),
        night_end=time(6, 0),
        min_points=1,
    )
    inside = [
        point(datetime(2026, 11, 18, 22, 0, tzinfo=BOGOTA)),
        point(datetime(2026, 11, 19, 5, 59, tzinfo=BOGOTA)),
    ]
    outside = [
        point(datetime(2026, 11, 18, 21, 59, tzinfo=BOGOTA)),
        point(datetime(2026, 11, 19, 6, 0, tzinfo=BOGOTA)),
    ]

    [night] = GlucoseWindowIterator(inside + outside, spec)

    assert len(night.points) == 2
    assert night.end - night.start == 8 * HOUR


def test_a_night_that_starts_after_midnight_stays_in_the_same_day() -> None:
    spec = WindowSpec.nocturnal(
        zone=BOGOTA,
        first_day=date(2026, 11, 18),
        days=2,
        night_start=time(0, 0),
        night_end=time(6, 0),
        min_points=1,
    )

    windows = list(GlucoseWindowIterator([], spec))

    assert [w.start.date() for w in windows] == [date(2026, 11, 18), date(2026, 11, 19)]
    assert all(w.end - w.start == 6 * HOUR for w in windows)


def test_a_fourteen_day_period_is_one_window() -> None:
    spec = WindowSpec.period(
        zone=BOGOTA, first_day=date(2026, 11, 1), span_days=14, min_points=2
    )
    points = [
        point(datetime(2026, 11, 1, 0, 0, tzinfo=BOGOTA)),
        point(datetime(2026, 11, 14, 23, 59, tzinfo=BOGOTA)),
        point(datetime(2026, 11, 15, 0, 0, tzinfo=BOGOTA)),
    ]

    [window] = GlucoseWindowIterator(points, spec)

    assert len(window.points) == 2
    assert window.has_enough_data
    assert window.end - window.start == timedelta(days=14)


def test_a_window_without_enough_data_is_marked() -> None:
    spec = WindowSpec.daily(
        zone=BOGOTA, first_day=date(2026, 11, 18), days=1, min_points=3
    )

    [window] = GlucoseWindowIterator(
        [point(datetime(2026, 11, 18, 8, 0, tzinfo=BOGOTA))], spec
    )

    assert not window.has_enough_data


def test_daylight_saving_days_have_23_and_25_hours() -> None:
    spring = daily(NEW_YORK, date(2026, 3, 8), 1, [])[0]
    autumn = daily(NEW_YORK, date(2026, 11, 1), 1, [])[0]
    normal = daily(NEW_YORK, date(2026, 6, 1), 1, [])[0]

    def length(window: GlucoseWindow) -> timedelta:
        return window.end.astimezone(UTC) - window.start.astimezone(UTC)

    assert length(spring) == 23 * HOUR
    assert length(autumn) == 25 * HOUR
    assert length(normal) == 24 * HOUR


def test_readings_come_out_sorted_whatever_the_input_order() -> None:
    base = datetime(2026, 11, 18, 8, 0, tzinfo=BOGOTA)
    shuffled = [point(base + 3 * HOUR), point(base), point(base + HOUR)]

    [window] = daily(BOGOTA, date(2026, 11, 18), 1, shuffled)

    assert [p.at for p in window.points] == sorted(p.at for p in shuffled)


def test_the_static_window_cuts_any_pair_of_instants() -> None:
    base = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
    points = [point(base), point(base + HOUR), point(base + 2 * HOUR)]

    window = GlucoseWindowIterator.window(points, base, base + 2 * HOUR, min_points=2)

    assert len(window.points) == 2
