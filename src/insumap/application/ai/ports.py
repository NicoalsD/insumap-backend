"""Ports of the AI client (P06 Adapter, P11 Proxy). Infrastructure implements them.

What leaves the backend is ``ForecastCall``: a pseudonym, the glucose series and
the thresholds of the patient. Never a name, a document, a contact or an id.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from insumap.application.metrics.forecast import (
    FallbackReason,
    ForecastExplanation,
    ForecastMode,
    ForecastPoint,
    ForecastRisk,
)
from insumap.domain.ai.linear_fallback import Trend


@final
class AiCallError(Exception):
    """The service could not answer a call; the proxy turns it into a fallback.

    ``counts_as_failure`` tells the circuit breaker whether the service is
    unhealthy (timeout, network, 5xx, bad token) or the request was wrong
    (``413``, ``422``), which is a defect of the backend and not of the service.
    """

    def __init__(self, reason: FallbackReason, *, counts_as_failure: bool) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.counts_as_failure = counts_as_failure


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastCall:
    """The minimized input of IA1 (Contrato-IA 8.1). Built only by the proxy."""

    subject_ref: str
    mode: ForecastMode
    timestamps: tuple[datetime, ...]
    values_mg_dl: tuple[Decimal, ...]
    interval_minutes: int
    horizons_minutes: tuple[int, ...]
    quantile_levels: tuple[float, ...]
    low_mg_dl: Decimal
    high_mg_dl: Decimal
    clinic_timezone: str
    night_start: str
    night_end: str


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteForecast:
    """What the service answered (or what its own fallback answered)."""

    model_name: str
    model_version: str
    input_hash: str
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None
    trend: Trend | None
    points: tuple[ForecastPoint, ...]
    risk: tuple[ForecastRisk, ...]
    explanation: ForecastExplanation | None


class AiServicePort(ABC):
    """``insumap-ai`` as the backend uses it (Contrato-IA)."""

    @abstractmethod
    def glucose_forecast(self, call: ForecastCall) -> RemoteForecast:
        """IA1. Raises ``AiCallError`` when the service did not answer usably."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastRecord:
    """One output of IA1 (or of its fallback), ready for ``ai.glucose_forecasts``."""

    clinic_id: UUID
    patient_id: UUID
    target_profile_id: UUID
    mode: ForecastMode
    output: RemoteForecast


class AiOutputStorePort(ABC):
    """Stores an AI output and the audit row of the data sent for it, atomically."""

    @abstractmethod
    def store_forecast(
        self, record: ForecastRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        """Write the output and its ``AI_PROCESSING`` audit row in one transaction."""
