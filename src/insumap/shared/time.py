"""Time source of the backend: the ``Clock`` port and its system implementation."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import ClassVar, Protocol, final, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Port that tells the current instant.

    Use cases and domain rules receive a ``Clock`` instead of reading the system
    time, so date rules are reproducible in tests with a fixed clock.
    """

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC ``datetime``."""
        ...


@final
class SystemClock:
    """The only place in the backend that reads the system clock. Always UTC.

    Production wires the single instance returned by ``SystemClock.instance()``.
    Direct construction is rejected so that no second instance can exist.

    Pattern: P01 Singleton
    """

    _instance: ClassVar[SystemClock | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _construction_token: ClassVar[object] = object()

    def __init__(self, construction_token: object = None) -> None:
        if construction_token is not SystemClock._construction_token:
            raise TypeError("SystemClock is a singleton: use SystemClock.instance()")

    @classmethod
    def instance(cls) -> SystemClock:
        """Return the single instance, creating it on first use (thread safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(cls._construction_token)
        return cls._instance

    def now(self) -> datetime:
        """Return the current instant in UTC, timezone aware."""
        return datetime.now(UTC)
