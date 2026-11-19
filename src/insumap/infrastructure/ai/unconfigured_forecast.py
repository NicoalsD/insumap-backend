"""Placeholder of the forecast port until the AI client branch is merged."""

from __future__ import annotations

from datetime import datetime
from typing import final, override
from uuid import UUID
from zoneinfo import ZoneInfo

from insumap.application.metrics.forecast import (
    AiUnavailableError,
    FallbackReason,
    ForecastMode,
    GlucoseForecast,
    GlucoseForecastPort,
)


@final
class UnconfiguredGlucoseForecastAdapter(GlucoseForecastPort):
    """Always unavailable, so every forecast answers the fallback ``AI_ERROR``.

    TODO(AI client): replace in ``container.py`` with the adapter over
    ``AiServicePort`` wrapped by ``RemoteAiServiceProxy``.
    """

    @override
    def forecast(
        self, patient_id: UUID, mode: ForecastMode, now: datetime, zone: ZoneInfo
    ) -> GlucoseForecast:
        raise AiUnavailableError(FallbackReason.AI_ERROR)
