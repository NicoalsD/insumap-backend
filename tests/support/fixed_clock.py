"""Deterministic clock for tests."""

from datetime import datetime, timedelta


class FixedClock:
    """Clock that always returns the same instant until it is advanced."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware instant")
        self._instant = instant

    def now(self) -> datetime:
        return self._instant

    def advance(self, delta: timedelta) -> None:
        self._instant += delta
