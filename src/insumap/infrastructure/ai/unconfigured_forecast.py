"""Forecast port that is always unavailable: a test double, not production wiring.

Production builds ``RemoteAiServiceProxy``, which answers with the rule-based
fallback when no service is configured. This class stays for tests that need an
AI that never answers.
"""

from __future__ import annotations

from typing import final, override

from insumap.application.metrics.forecast import (
    AiUnavailableError,
    FallbackReason,
    ForecastRequest,
    GlucoseForecast,
    GlucoseForecastPort,
)


@final
class UnconfiguredGlucoseForecastAdapter(GlucoseForecastPort):
    """Always unavailable, so every forecast answers the fallback ``AI_ERROR``."""

    @override
    def forecast(self, request: ForecastRequest) -> GlucoseForecast:
        del request
        raise AiUnavailableError(FallbackReason.AI_ERROR)
