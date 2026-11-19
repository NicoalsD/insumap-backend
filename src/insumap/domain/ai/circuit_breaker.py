"""The circuit breaker of the AI client (P18 State): CLOSED, OPEN and HALF_OPEN.

``CLOSED`` lets every call through and counts consecutive failures; at the
threshold it opens. ``OPEN`` refuses calls until the open period ends, then the
next caller becomes the single probe of ``HALF_OPEN``. The probe's answer closes
the circuit (success) or opens it again (failure). The time comes from the
caller (the ``Clock``), so the machine never reads the system clock.

Only the calls that reach the service count: a refused call is not a failure.
The state lives in memory, one per process (Contrato-IA 5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import ClassVar, final, override


class CircuitStatus(StrEnum):
    """The stored name of a state, for logs and tests."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CircuitPolicy:
    """Thresholds of the breaker, from ``Settings`` (never written in code)."""

    failure_threshold: int
    open_for: timedelta

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("the failure threshold must be at least 1")
        if self.open_for <= timedelta(0):
            raise ValueError("the open period must be positive")


class CircuitBreakerState(ABC):
    """Base of the breaker machine. Each method returns the next state.

    ``admit`` answers whether a call may go to the service; ``succeed`` and
    ``fail`` report the answer of a call that was admitted.

    Pattern: P18 State
    """

    status: ClassVar[CircuitStatus]

    @abstractmethod
    def admit(
        self, now: datetime, policy: CircuitPolicy
    ) -> tuple[CircuitBreakerState, bool]:
        """The next state and whether this call may reach the service."""

    @abstractmethod
    def succeed(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        """An admitted call answered normally."""

    @abstractmethod
    def fail(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        """An admitted call failed (timeout, network, 5xx, bad token)."""

    @staticmethod
    def closed() -> CircuitBreakerState:
        """A circuit with no failures yet."""
        return ClosedCircuitState(consecutive_failures=0)


@final
@dataclass(frozen=True, slots=True)
class ClosedCircuitState(CircuitBreakerState):
    consecutive_failures: int

    status: ClassVar[CircuitStatus] = CircuitStatus.CLOSED

    @override
    def admit(
        self, now: datetime, policy: CircuitPolicy
    ) -> tuple[CircuitBreakerState, bool]:
        del now, policy
        return self, True

    @override
    def succeed(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        del now, policy
        return ClosedCircuitState(consecutive_failures=0)

    @override
    def fail(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        failures = self.consecutive_failures + 1
        if failures >= policy.failure_threshold:
            return OpenCircuitState(opened_at=now)
        return ClosedCircuitState(consecutive_failures=failures)


@final
@dataclass(frozen=True, slots=True)
class OpenCircuitState(CircuitBreakerState):
    opened_at: datetime

    status: ClassVar[CircuitStatus] = CircuitStatus.OPEN

    @override
    def admit(
        self, now: datetime, policy: CircuitPolicy
    ) -> tuple[CircuitBreakerState, bool]:
        if now - self.opened_at < policy.open_for:
            return self, False
        # The first caller after the open period is the probe; the others wait.
        return HalfOpenCircuitState(), True

    @override
    def succeed(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        del now, policy
        return self

    @override
    def fail(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        del policy
        return OpenCircuitState(opened_at=now)


@final
@dataclass(frozen=True, slots=True)
class HalfOpenCircuitState(CircuitBreakerState):
    """Exists while the single probe call is in flight."""

    status: ClassVar[CircuitStatus] = CircuitStatus.HALF_OPEN

    @override
    def admit(
        self, now: datetime, policy: CircuitPolicy
    ) -> tuple[CircuitBreakerState, bool]:
        del now, policy
        return self, False

    @override
    def succeed(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        del now, policy
        return ClosedCircuitState(consecutive_failures=0)

    @override
    def fail(self, now: datetime, policy: CircuitPolicy) -> CircuitBreakerState:
        del policy
        return OpenCircuitState(opened_at=now)


@final
class CircuitBreaker:
    """Holds the current state and applies the policy. Not thread safe by itself.

    The proxy that owns it serializes the calls with a lock.
    """

    def __init__(self, policy: CircuitPolicy) -> None:
        self._policy = policy
        self._state: CircuitBreakerState = CircuitBreakerState.closed()

    @property
    def status(self) -> CircuitStatus:
        return self._state.status

    def allow(self, now: datetime) -> bool:
        """Whether a call may go to the service now."""
        self._state, allowed = self._state.admit(now, self._policy)
        return allowed

    def record_success(self, now: datetime) -> None:
        self._state = self._state.succeed(now, self._policy)

    def record_failure(self, now: datetime) -> None:
        self._state = self._state.fail(now, self._policy)
