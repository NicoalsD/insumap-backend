from datetime import UTC, datetime, timedelta

import pytest

from insumap.shared.time import Clock, SystemClock
from tests.support.fixed_clock import FixedClock


def test_instance_returns_the_same_object_every_time() -> None:
    assert SystemClock.instance() is SystemClock.instance()


def test_now_is_timezone_aware_utc() -> None:
    now = SystemClock.instance().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_now_follows_the_system_time() -> None:
    before = datetime.now(UTC)
    now = SystemClock.instance().now()
    after = datetime.now(UTC)

    assert before <= now <= after


def test_direct_construction_is_rejected() -> None:
    with pytest.raises(TypeError, match=r"SystemClock\.instance\(\)"):
        SystemClock()


def test_construction_with_a_foreign_token_is_rejected() -> None:
    with pytest.raises(TypeError):
        SystemClock(object())


def test_system_clock_satisfies_the_clock_port() -> None:
    assert isinstance(SystemClock.instance(), Clock)


def test_fixed_clock_satisfies_the_clock_port_and_can_advance() -> None:
    start = datetime(2026, 1, 15, 8, 30, tzinfo=UTC)
    clock = FixedClock(start)

    clock.advance(timedelta(minutes=15))

    assert isinstance(clock, Clock)
    assert clock.now() == start + timedelta(minutes=15)


def test_fixed_clock_rejects_naive_instants() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 1, 15, 8, 30))
