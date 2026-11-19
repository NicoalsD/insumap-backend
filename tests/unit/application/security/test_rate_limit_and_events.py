from datetime import timedelta

import pytest

from insumap.application.security.events import SecurityEventType, SecuritySeverity
from insumap.application.security.rate_limit import (
    RateLimitCheck,
    RateLimitDecision,
    RateLimitedError,
    RateLimiterPort,
    RateLimitRule,
)

RULE = RateLimitRule(family="login", limit=2, window=timedelta(minutes=1))
OTHER = RateLimitRule(family="other", limit=1, window=timedelta(minutes=1))


class ScriptedLimiter(RateLimiterPort):
    def __init__(self, blocked: set[str]) -> None:
        self.blocked = blocked
        self.calls: list[tuple[str, str]] = []

    def hit(self, rule: RateLimitRule, subject: str) -> RateLimitDecision:
        self.calls.append((rule.family, subject))
        return RateLimitDecision(
            allowed=rule.family not in self.blocked, retry_after_seconds=42
        )


def test_check_passes_when_every_rule_allows() -> None:
    limiter = ScriptedLimiter(set())

    RateLimitCheck(limiter, RULE, OTHER).ensure("1.2.3.4")

    assert limiter.calls == [("login", "1.2.3.4"), ("other", "1.2.3.4")]


def test_check_raises_with_retry_after_on_the_first_exceeded_rule() -> None:
    limiter = ScriptedLimiter({"login"})

    with pytest.raises(RateLimitedError) as caught:
        RateLimitCheck(limiter, RULE, OTHER).ensure("1.2.3.4")

    assert caught.value.headers == {"Retry-After": "42"}
    assert limiter.calls == [("login", "1.2.3.4")]


def test_every_event_type_has_a_severity() -> None:
    for event_type in SecurityEventType:
        assert isinstance(event_type.severity, SecuritySeverity)
    assert SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED.severity is (
        SecuritySeverity.HIGH
    )
