"""Ports and models of the AI calls for risk (IA2), clinical summaries (IA5) and the
assistant (IA6).

Every call goes through ``RemoteAiServiceProxy`` (P11), which implements these
ports: it minimizes the request (only ``subject_ref``), decides between the
service and the rules or template fallback, and stores the output with its audit
row. The use cases never call the service directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, final
from uuid import UUID

from insumap.application.metrics.forecast import FallbackReason
from insumap.domain.ai.risk import RiskFeatures, RiskLimits, RiskTier
from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics


class EscalationLevel(StrEnum):
    """How the assistant escalates (``ai.assistant_messages.escalation_level``)."""

    NONE = "NONE"
    CONTACT_DOCTOR = "CONTACT_DOCTOR"
    EMERGENCY = "EMERGENCY"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AiExplanation:
    """What the doctor reads about an output. ``factors`` and ``data_refs`` are plain
    maps."""

    summary: str
    factors: tuple[Mapping[str, Any], ...] = ()
    data_refs: tuple[Mapping[str, Any], ...] = ()


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskRequest:
    """The minimized input of IA2 plus what the rules need. Built by the use case."""

    patient_id: UUID
    clinic_id: UUID
    target_profile_id: UUID
    window_days: int
    diabetes_type: str
    """Database code (``T1D``, ``T2D``, ``GDM`` or ``OTHER``); the proxy maps it."""
    features: RiskFeatures
    limits: RiskLimits
    is_sufficient: bool
    window_start: datetime
    window_end: datetime


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskResult:
    """An IA2 output, from the service or from the rules, with its model trail."""

    model_name: str
    model_version: str
    input_hash: str
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None
    risk_probability: Decimal | None
    risk_tier: RiskTier | None
    calibrated: bool
    window_days: int
    explanation: AiExplanation


class RiskAssessmentPort(ABC):
    """Scores a patient's risk of deterioration (IA2), or answers with the rules."""

    @abstractmethod
    def assess(self, request: RiskRequest) -> RiskResult:
        """The output of the service or of the rules, stored before it returns."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryRequest:
    """What the summary is made of: numbers and enums only, never free text."""

    patient_id: UUID
    clinic_id: UUID
    target_profile_id: UUID
    requested_by: UUID
    period_start: datetime
    period_end: datetime
    diabetes_type: str
    metrics: GlycemicMetrics
    target_tir_pct: Decimal
    is_sufficient: bool
    use_llm: bool
    """``False`` for a non demo clinic without ``LLM_REAL_DATA_ALLOWED``: template
    only."""
    readings_per_day: Decimal | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SummarySection:
    title: str
    text: str
    refs: tuple[str, ...]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryResult:
    """A clinical summary, from the LLM or from the deterministic template."""

    summary_id: UUID
    period_start: datetime
    period_end: datetime
    model_name: str
    model_version: str
    input_hash: str
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None
    summary_text: str
    sections: tuple[SummarySection, ...]
    numeric_check_matched: bool
    explanation: AiExplanation


class ClinicalSummaryPort(ABC):
    """Writes the pre-visit summary (IA5), or answers with the template."""

    @abstractmethod
    def summarize(self, request: SummaryRequest) -> SummaryResult:
        """The output of the LLM or of the template, stored before it returns."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantTurn:
    """One turn of the conversation sent with a new message (Contrato-IA 8.6)."""

    sender: str
    text: str


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovedFragment:
    """A fragment of approved clinic material the assistant may cite."""

    doc_id: UUID
    title: str
    text: str


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantRequest:
    """The minimized turn of IA6. The consent is checked before the proxy is called."""

    clinic_id: UUID
    patient_id: UUID
    conversation_id: UUID
    message: str
    history: tuple[AssistantTurn, ...]
    fragments: tuple[ApprovedFragment, ...]
    external_consent_id: UUID | None
    """The ``ai_external_processing`` consent that allows the call, or ``None``."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantResult:
    """The reply of the assistant, from the service or the predefined text."""

    conversation_id: UUID
    reply_text: str
    citations: tuple[UUID, ...]
    escalation: EscalationLevel
    escalation_message: str | None
    guardrails_triggered: tuple[str, ...]
    model_name: str | None
    model_version: str | None
    input_hash: str | None
    explanation: AiExplanation | None
    is_fallback: bool
    fallback_reason: FallbackReason | None
    generated_at: datetime


class AssistantPort(ABC):
    """Answers a patient question (IA6), or with the predefined text."""

    @abstractmethod
    def reply(self, request: AssistantRequest) -> AssistantResult:
        """The reply of the service or the predefined text, stored before it returns."""
