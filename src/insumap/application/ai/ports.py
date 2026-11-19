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

from insumap.application.ai.assessments import (
    AiExplanation,
    ApprovedFragment,
    AssistantResult,
    AssistantTurn,
    EscalationLevel,
    RiskResult,
    SummaryResult,
    SummarySection,
)
from insumap.application.metrics.forecast import (
    FallbackReason,
    ForecastExplanation,
    ForecastMode,
    ForecastPoint,
    ForecastRisk,
)
from insumap.domain.ai.linear_fallback import Trend
from insumap.domain.ai.risk import RiskFeatures, RiskTier
from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics


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


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskCall:
    """The minimized input of IA2 (Contrato-IA 8.2). Built only by the proxy."""

    subject_ref: str
    window_days: int
    diabetes_type: str
    """The contract value (``T1D``, ``T2D`` or ``GESTATIONAL``)."""
    target_tir_pct: Decimal
    features: RiskFeatures


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryCall:
    """The minimized input of IA5 (Contrato-IA 8.5): figures and enums, no free text."""

    subject_ref: str
    period_start: datetime
    period_end: datetime
    diabetes_type: str
    metrics: GlycemicMetrics
    target_tir_pct: Decimal
    readings_per_day: Decimal | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantCall:
    """The minimized input of IA6 (Contrato-IA 8.6): the pseudonym and the turn."""

    subject_ref: str
    message: str
    history: tuple[AssistantTurn, ...]
    fragments: tuple[ApprovedFragment, ...]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteRisk:
    """What the service answered for IA2 (or what its own fallback answered)."""

    model_name: str
    model_version: str
    input_hash: str
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None
    risk_probability: Decimal | None
    risk_tier: RiskTier | None
    calibrated: bool
    explanation: AiExplanation


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteSummary:
    """What the service answered for IA5."""

    model_name: str
    model_version: str
    input_hash: str
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None
    summary_text: str
    sections: tuple[SummarySection, ...]
    numeric_all_matched: bool
    explanation: AiExplanation


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteAssistant:
    """What the service answered for IA6. ``citations`` are the ids it echoed."""

    model_name: str
    model_version: str
    input_hash: str
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None
    reply_text: str
    citations: tuple[str, ...]
    escalation: EscalationLevel
    escalation_message: str | None
    guardrails_triggered: tuple[str, ...]
    explanation: AiExplanation


class AiServicePort(ABC):
    """``insumap-ai`` as the backend uses it (Contrato-IA)."""

    @abstractmethod
    def glucose_forecast(self, call: ForecastCall) -> RemoteForecast:
        """IA1. Raises ``AiCallError`` when the service did not answer usably."""

    @abstractmethod
    def risk_assessment(self, call: RiskCall) -> RemoteRisk:
        """IA2. Raises ``AiCallError`` when the service did not answer usably."""

    @abstractmethod
    def clinical_summary(self, call: SummaryCall) -> RemoteSummary:
        """IA5. Raises ``AiCallError`` when the service did not answer usably."""

    @abstractmethod
    def assistant_reply(self, call: AssistantCall) -> RemoteAssistant:
        """IA6. Raises ``AiCallError`` when the service did not answer usably."""


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

    @abstractmethod
    def store_risk(
        self, record: RiskRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        """Write an IA2 assessment and its audit row in one transaction."""

    @abstractmethod
    def store_summary(
        self, record: SummaryRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        """Write an IA5 summary and its audit row in one transaction."""

    @abstractmethod
    def store_assistant_reply(
        self, record: AssistantRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        """Write an IA6 reply and its audit row in one transaction."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRecord:
    """One IA2 assessment ready for ``ai.risk_assessments`` (DETERIORATION)."""

    clinic_id: UUID
    patient_id: UUID
    target_profile_id: UUID
    window_days: int
    output: RiskResult


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryRecord:
    """One IA5 summary ready for ``ai.clinical_summaries`` (the id is in the output)."""

    clinic_id: UUID
    patient_id: UUID
    requested_by: UUID
    output: SummaryResult


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantRecord:
    """One IA6 reply ready for ``ai.assistant_messages`` (sender ``ASSISTANT``)."""

    reply_id: UUID
    clinic_id: UUID
    patient_id: UUID
    output: AssistantResult
    context_doc_ids: tuple[UUID, ...]
    external_consent_id: UUID | None
