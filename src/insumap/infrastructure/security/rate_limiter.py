"""In-memory fixed window rate limiter (one process)."""

from __future__ import annotations

import math
import threading
from datetime import datetime
from typing import final, override

from insumap.application.security.rate_limit import (
    RateLimitDecision,
    RateLimiterPort,
    RateLimitRule,
)
from insumap.shared.time import Clock


@final
class InMemoryRateLimiter(RateLimiterPort):
    """Counts hits per ``(family, subject)`` in fixed windows of the rule.

    The counters live in this process, so each API instance counts its own
    traffic; the shared PostgreSQL buckets of the policy are pending. Expired
    windows are dropped when they are seen.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], tuple[datetime, int]] = {}

    @override
    def hit(self, rule: RateLimitRule, subject: str) -> RateLimitDecision:
        now = self._clock.now()
        key = (rule.family, subject)
        with self._lock:
            started, hits = self._windows.get(key, (now, 0))
            if now - started >= rule.window:
                started, hits = now, 0
            hits += 1
            self._windows[key] = (started, hits)
        if hits <= rule.limit:
            return RateLimitDecision(allowed=True, retry_after_seconds=0)
        remaining = (started + rule.window - now).total_seconds()
        return RateLimitDecision(
            allowed=False, retry_after_seconds=max(1, math.ceil(remaining))
        )
