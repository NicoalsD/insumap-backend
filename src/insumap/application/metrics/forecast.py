"""Glucose forecast of a patient (IA1): the port to the AI and the safe fallback.

The AI client is built by another branch. This module only fixes what the API
promises (docs/API.md 8.8): reading a forecast never fails because the AI does.
If the service is down, slow or not configured, the answer is ``200`` with
``is_fallback: true`` and the reason; with too little data the AI is not even
called. The result never contains an insulin dose.

TODO(AI client): build ``GlucoseForecastPort`` over ``AiServicePort`` and wrap it
with ``RemoteAiServiceProxy`` (3 s timeout, circuit breaker, linear fallback),
save every output in ``ai.glucose_forecasts`` and replace the placeholder
``UnconfiguredGlucoseForecastAdapter`` in ``container.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import final
from uuid import UUID
from zoneinfo import ZoneInfo

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWorkPort,
)
from insumap.application.metrics.metrics import (
    MetricWindow,
    metrics_for,
    period_of,
)
from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.glycemic_metrics import Signal
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock


class ForecastMode(StrEnum):
    SHORT_TERM = "SHORT_TERM"
    OVERNIGHT = "OVERNIGHT"


class FallbackReason(StrEnum):
    AI_TIMEOUT = "AI_TIMEOUT"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    AI_ERROR = "AI_ERROR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Trend(StrEnum):
    FALLING = "FALLING"
    STABLE = "STABLE"
    RISING = "RISING"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastPoint:
    horizon_minutes: int
    timestamp: datetime
    p10: Decimal
    p50: Decimal
    p90: Decimal


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastRisk:
    horizon_minutes: int
    hypo_probability: Decimal
    hyper_probability: Decimal


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastExplanation:
    summary: str
    factors: tuple[str, ...]
    data_refs: tuple[str, ...]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseForecast:
    """What the AI (or its fallback) says about the next hours. No doses, ever."""

    mode: ForecastMode
    generated_at: datetime
    model_name: str | None
    model_version: str | None
    is_fallback: bool
    fallback_reason: FallbackReason | None
    trend: Trend | None
    points: tuple[ForecastPoint, ...]
    risk: tuple[ForecastRisk, ...]
    explanation: ForecastExplanation | None


class AiUnavailableError(Exception):
    """The AI could not answer: its client turns this into a fallback reason.

    It never reaches the HTTP layer; ``GetForecastUseCase`` catches it.
    """

    def __init__(self, reason: FallbackReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class GlucoseForecastPort(ABC):
    """Asks the AI for a forecast of a patient (IA1) with a pseudonym only."""

    @abstractmethod
    def forecast(
        self, patient_id: UUID, mode: ForecastMode, now: datetime, zone: ZoneInfo
    ) -> GlucoseForecast:
        """The forecast, or raise ``AiUnavailableError`` with the fallback reason."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ForecastInput:
    actor: Actor
    mode: ForecastMode = ForecastMode.SHORT_TERM
    patient_id: UUID | None = None


@final
class GetForecastUseCase:
    """``GET /patients/{patient_id}/forecast`` and ``GET /patients/own/forecast``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        targets: TargetProfilePort,
        series: GlucoseSeriesPort,
        forecasts: GlucoseForecastPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._own_gate = own_gate
        self._assigned_gate = assigned_gate
        self._targets = targets
        self._series = series
        self._forecasts = forecasts
        self._clock = clock

    def execute(self, input: ForecastInput) -> GlucoseForecast:
        """The forecast, or the fallback with the reason; never a ``5xx``."""
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)):
            if input.patient_id is None:
                patient_id = self._own_gate.enter(
                    actor, PermissionCode.AI_FORECASTS_READ_OWN
                ).patient_id
            else:
                patient_id = self._assigned_gate.enter(
                    actor,
                    PermissionCode.AI_FORECASTS_READ_ASSIGNED,
                    input.patient_id,
                )
            found = self._targets.for_patient(patient_id)
            if found is None:
                raise InsumapError(ErrorCode.INTERNAL_ERROR)
            now = self._clock.now()
            zone = ZoneInfo(found.timezone)
            period = period_of(MetricWindow.LAST_24_HOURS, now, zone)
            points = list(self._series.points(patient_id, period.start, period.end))
            recent = metrics_for(period, points, found.profile)
        if recent.signal is not Signal.CGM or not recent.is_sufficient:
            return self._fallback(input.mode, FallbackReason.INSUFFICIENT_DATA)
        try:
            return self._forecasts.forecast(patient_id, input.mode, now, zone)
        except AiUnavailableError as error:
            return self._fallback(input.mode, error.reason)

    def _fallback(self, mode: ForecastMode, reason: FallbackReason) -> GlucoseForecast:
        return GlucoseForecast(
            mode=mode,
            generated_at=self._clock.now(),
            model_name=None,
            model_version=None,
            is_fallback=True,
            fallback_reason=reason,
            trend=None,
            points=(),
            risk=(),
            explanation=None,
        )
