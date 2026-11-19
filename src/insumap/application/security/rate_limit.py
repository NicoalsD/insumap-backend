"""Rate limits of the sensitive endpoints, behind a port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, final

from insumap.shared.errors import ErrorCode, InsumapError

RETRY_AFTER_HEADER: Final = "Retry-After"


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitRule:
    """At most ``limit`` hits per ``window`` for one subject of a family."""

    family: str
    limit: int
    window: timedelta


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitDecision:
    """Whether a hit is allowed and, if not, how long to wait."""

    allowed: bool
    retry_after_seconds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class RateLimitRules:
    """The rules of the identity endpoints, built once from ``Settings``."""

    login_per_ip: RateLimitRule
    mfa_per_ip: RateLimitRule
    activation_per_ip_per_minute: RateLimitRule
    activation_per_ip_per_hour: RateLimitRule
    refresh_per_user: RateLimitRule


class RateLimiterPort(ABC):
    """Counts hits per rule and subject."""

    @abstractmethod
    def hit(self, rule: RateLimitRule, subject: str) -> RateLimitDecision:
        """Count one hit for ``subject`` and say whether it is allowed."""


@final
class RateLimitedError(InsumapError):
    """Too many requests; the answer carries ``Retry-After``."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            ErrorCode.RATE_LIMITED,
            headers={RETRY_AFTER_HEADER: str(retry_after_seconds)},
        )


@final
class RateLimitCheck:
    """The rate limit of one action: raises ``RateLimitedError`` when exceeded."""

    def __init__(self, limiter: RateLimiterPort, *rules: RateLimitRule) -> None:
        self._limiter = limiter
        self._rules = rules

    def ensure(self, subject: str) -> None:
        """Count a hit on every rule; fail on the first one exceeded."""
        for rule in self._rules:
            decision = self._limiter.hit(rule, subject)
            if not decision.allowed:
                raise RateLimitedError(decision.retry_after_seconds)
