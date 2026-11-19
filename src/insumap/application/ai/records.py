"""Ports over the AI tables that the endpoints read or extend (API.md 8.10).

The rows are written by the AI calls (``RemoteAiServiceProxy``) and by the
assistant use case. These ports read them under row level security: a doctor
sees the clinic's rows and the use cases filter them to the assigned patients.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, final
from uuid import UUID

from insumap.application.ai.assessments import (
    AiExplanation,
    ApprovedFragment,
    AssistantTurn,
    SummarySection,
)
from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.ai.risk import RiskTier


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PatternFindingView:
    """One finding of IA3 as stored (``ai.pattern_findings``)."""

    finding_id: UUID
    patient_id: UUID
    pattern_type: str
    window_start: datetime
    window_end: datetime
    confidence: Decimal | None
    evidence: Mapping[str, Any]
    explanation: AiExplanation
    model_version: str
    is_fallback: bool
    fallback_reason: str | None
    generated_at: datetime


class PatternFindingReadPort(ABC):
    """The findings of one patient, newest first (the assigned gate runs before)."""

    @abstractmethod
    def list_for_patient(
        self, patient_id: UUID, page: PageRequest
    ) -> Page[PatternFindingView]:
        """One page of findings of the patient."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class DropoutRiskView:
    """The latest dropout assessment of an assigned patient, without clinical values."""

    patient_id: UUID
    patient_name: str
    risk_tier: RiskTier | None
    explanation: AiExplanation
    is_fallback: bool
    fallback_reason: str | None
    generated_at: datetime


class DropoutRiskReadPort(ABC):
    """The dropout assessments of the patients assigned to one doctor."""

    @abstractmethod
    def list_for_doctor(
        self, doctor_id: UUID, *, tier: RiskTier | None, page: PageRequest
    ) -> Page[DropoutRiskView]:
        """One page of the latest dropout assessment per assigned patient."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicalSummaryView:
    """A stored pre-visit summary (``ai.clinical_summaries``)."""

    summary_id: UUID
    patient_id: UUID
    period_start: datetime
    period_end: datetime
    summary_text: str
    sections: tuple[SummarySection, ...]
    numeric_check_matched: bool | None
    model_version: str
    is_fallback: bool
    fallback_reason: str | None
    generated_at: datetime


class ClinicalSummaryReadPort(ABC):
    """The summaries the session may see."""

    @abstractmethod
    def get(self, summary_id: UUID) -> ClinicalSummaryView | None:
        """The summary, or ``None`` when the session may not see it."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AiEvaluationFilter:
    use_case: str | None = None
    model_version: str | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AiEvaluationView:
    """An evaluation of one use case against its fallback (aggregated metrics only)."""

    evaluation_id: UUID
    use_case: str
    model_name: str
    model_version: str
    baseline_name: str
    cohort_ref: str
    sample_size: int
    model_metrics: Mapping[str, Any]
    baseline_metrics: Mapping[str, Any]
    fallback_usage_pct: Decimal | None
    evaluated_at: datetime


class AiEvaluationReadPort(ABC):
    """The evaluations the session may see (RLS decides the clinic)."""

    @abstractmethod
    def list(
        self, filters: AiEvaluationFilter, page: PageRequest
    ) -> Page[AiEvaluationView]:
        """One page, newest first."""


class PatientAiProfilePort(ABC):
    """The diabetes type of a patient, as the AI contract spells it."""

    @abstractmethod
    def diabetes_type(self, patient_id: UUID) -> str | None:
        """The database code (``T1D``, ``T2D``, ``GDM`` or ``OTHER``), or ``None``."""


class AssistantConversationPort(ABC):
    """The turns of the patient's assistant conversations
    (``ai.assistant_messages``)."""

    @abstractmethod
    def history(
        self, patient_id: UUID, conversation_id: UUID, *, limit: int
    ) -> tuple[AssistantTurn, ...]:
        """The last ``limit`` turns of a conversation, oldest first."""

    @abstractmethod
    def add_patient_message(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        conversation_id: UUID,
        content: str,
        sent_at: datetime,
    ) -> UUID:
        """Write the patient's turn; the caller's transaction commits it."""


class ApprovedKnowledgePort(ABC):
    """Approved clinic material the assistant may use as context (RAG, Modulo-IA
    6.6)."""

    @abstractmethod
    def search(
        self, keywords: Sequence[str], *, limit: int, max_chars: int
    ) -> tuple[ApprovedFragment, ...]:
        """Approved documents that match any keyword, most relevant first."""
