"""SQL reads of the AI tables and the assistant's conversation, under row level
security.

Each class answers one port of ``application/ai/records.py``. The session is the
caller's, so the policies decide what each role sees; the doctor's assigned
patients are filtered here, as ``RecommendationRepository`` does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, final, override
from uuid import UUID

from sqlalchemy import and_, func, or_, select

from insumap.application.ai.assessments import (
    AiExplanation,
    ApprovedFragment,
    AssistantTurn,
    SummarySection,
)
from insumap.application.ai.records import (
    AiEvaluationFilter,
    AiEvaluationReadPort,
    AiEvaluationView,
    ApprovedKnowledgePort,
    AssistantConversationPort,
    ClinicalSummaryReadPort,
    ClinicalSummaryView,
    DropoutRiskReadPort,
    DropoutRiskView,
    PatientAiProfilePort,
    PatternFindingReadPort,
    PatternFindingView,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.ai.risk import RiskTier
from insumap.infrastructure.persistence.orm import (
    AiEvaluationOrm,
    AssistantMessageOrm,
    CareAssignmentOrm,
    ClinicalSummaryOrm,
    KnowledgeDocumentOrm,
    PatientOrm,
    PatternFindingOrm,
    RiskAssessmentOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

DROPOUT: str = "DROPOUT"
APPROVED: str = "APPROVED"


@final
class SqlPatternFindingReads(PatternFindingReadPort):
    """``ai.pattern_findings`` of one patient, newest first."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def list_for_patient(
        self, patient_id: UUID, page: PageRequest
    ) -> Page[PatternFindingView]:
        statement = (
            select(PatternFindingOrm)
            .where(
                PatternFindingOrm.patient_id == patient_id,
                PatternFindingOrm.is_shadow.is_(False),
            )
            .order_by(PatternFindingOrm.id.desc())
        )
        if page.after is not None:
            statement = statement.where(PatternFindingOrm.id < page.after)
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_finding(row) for row in rows],
            limit=page.limit,
            key=lambda item: item.finding_id,
        )


@final
class SqlDropoutRiskReads(DropoutRiskReadPort):
    """The latest dropout assessment of each patient assigned to the doctor."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def list_for_doctor(
        self, doctor_id: UUID, *, tier: RiskTier | None, page: PageRequest
    ) -> Page[DropoutRiskView]:
        assigned = select(CareAssignmentOrm.patient_id).where(
            CareAssignmentOrm.doctor_user_id == doctor_id,
            CareAssignmentOrm.ended_at.is_(None),
        )
        latest = (
            select(
                RiskAssessmentOrm.patient_id.label("patient_id"),
                func.max(RiskAssessmentOrm.generated_at).label("generated_at"),
            )
            .where(
                RiskAssessmentOrm.assessment_type == DROPOUT,
                RiskAssessmentOrm.is_shadow.is_(False),
                RiskAssessmentOrm.patient_id.in_(assigned),
            )
            .group_by(RiskAssessmentOrm.patient_id)
            .subquery()
        )
        statement = (
            select(RiskAssessmentOrm, PatientOrm.full_name)
            .join(
                latest,
                and_(
                    RiskAssessmentOrm.patient_id == latest.c.patient_id,
                    RiskAssessmentOrm.generated_at == latest.c.generated_at,
                ),
            )
            .join(PatientOrm, PatientOrm.id == RiskAssessmentOrm.patient_id)
            .where(RiskAssessmentOrm.assessment_type == DROPOUT)
            .order_by(RiskAssessmentOrm.patient_id.desc())
        )
        if tier is not None:
            statement = statement.where(RiskAssessmentOrm.risk_tier == tier.value)
        if page.after is not None:
            statement = statement.where(RiskAssessmentOrm.patient_id < page.after)
        rows = self._current.get().execute(statement.limit(page.limit + 1)).all()
        return build_page(
            [_dropout(row, name) for row, name in rows],
            limit=page.limit,
            key=lambda item: item.patient_id,
        )


@final
class SqlClinicalSummaryReads(ClinicalSummaryReadPort):
    """``ai.clinical_summaries`` by id; the session's policies decide visibility."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, summary_id: UUID) -> ClinicalSummaryView | None:
        row = self._current.get().get(ClinicalSummaryOrm, summary_id)
        return None if row is None else _summary(row)


@final
class SqlAiEvaluationReads(AiEvaluationReadPort):
    """``ai.ai_evaluations`` of the clinic, newest first."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def list(
        self, filters: AiEvaluationFilter, page: PageRequest
    ) -> Page[AiEvaluationView]:
        statement = select(AiEvaluationOrm).order_by(AiEvaluationOrm.id.desc())
        if filters.use_case is not None:
            statement = statement.where(AiEvaluationOrm.use_case == filters.use_case)
        if filters.model_version is not None:
            statement = statement.where(
                AiEvaluationOrm.model_version == filters.model_version
            )
        if page.after is not None:
            statement = statement.where(AiEvaluationOrm.id < page.after)
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_evaluation(row) for row in rows],
            limit=page.limit,
            key=lambda item: item.evaluation_id,
        )


@final
class SqlPatientAiProfile(PatientAiProfilePort):
    """The diabetes type of a patient, read under the session's policies."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def diabetes_type(self, patient_id: UUID) -> str | None:
        return self._current.get().scalar(
            select(PatientOrm.diabetes_type).where(PatientOrm.id == patient_id)
        )


@final
class SqlAssistantConversation(AssistantConversationPort):
    """The turns of a conversation and the patient's own new turn."""

    def __init__(self, current: CurrentSession, ids: IdGenerator) -> None:
        self._current = current
        self._ids = ids

    @override
    def history(
        self, patient_id: UUID, conversation_id: UUID, *, limit: int
    ) -> tuple[AssistantTurn, ...]:
        rows = (
            self._current.get()
            .scalars(
                select(AssistantMessageOrm)
                .where(
                    AssistantMessageOrm.patient_id == patient_id,
                    AssistantMessageOrm.conversation_id == conversation_id,
                )
                .order_by(AssistantMessageOrm.sent_at.desc())
                .limit(limit)
            )
            .all()
        )
        return tuple(
            AssistantTurn(sender=row.sender, text=row.content) for row in reversed(rows)
        )

    @override
    def add_patient_message(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        conversation_id: UUID,
        content: str,
        sent_at: datetime,
    ) -> UUID:
        message_id = self._ids.new_id()
        self._current.get().add(
            AssistantMessageOrm(
                id=message_id,
                clinic_id=clinic_id,
                patient_id=patient_id,
                conversation_id=conversation_id,
                sender="PATIENT",
                content=content,
                escalation_level=None,
                guardrails_triggered=[],
                context_doc_ids=[],
                external_consent_id=None,
                model_name=None,
                model_version=None,
                input_hash=None,
                explanation=None,
                is_fallback=False,
                fallback_reason=None,
                sent_at=sent_at,
            )
        )
        self._current.get().flush()
        return message_id


@final
class SqlApprovedKnowledge(ApprovedKnowledgePort):
    """Approved clinic material whose title or body contains a keyword (RAG, sin
    vector)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def search(
        self, keywords: Sequence[str], *, limit: int, max_chars: int
    ) -> tuple[ApprovedFragment, ...]:
        if not keywords:
            return ()
        matches = or_(
            *(
                or_(
                    KnowledgeDocumentOrm.title.ilike(f"%{word}%"),
                    KnowledgeDocumentOrm.body.ilike(f"%{word}%"),
                )
                for word in keywords
            )
        )
        rows = (
            self._current.get()
            .scalars(
                select(KnowledgeDocumentOrm)
                .where(KnowledgeDocumentOrm.status == APPROVED, matches)
                .order_by(KnowledgeDocumentOrm.id.desc())
                .limit(limit)
            )
            .all()
        )
        return tuple(
            ApprovedFragment(doc_id=row.id, title=row.title, text=row.body[:max_chars])
            for row in rows
        )


def _explanation(raw: Mapping[str, Any] | None) -> AiExplanation:
    data = dict(raw or {})
    return AiExplanation(
        summary=str(data.get("summary", "")),
        factors=tuple(dict(item) for item in data.get("factors", [])),
        data_refs=tuple(dict(item) for item in data.get("data_refs", [])),
    )


def _finding(row: PatternFindingOrm) -> PatternFindingView:
    return PatternFindingView(
        finding_id=row.id,
        patient_id=row.patient_id,
        pattern_type=row.pattern_type,
        window_start=row.window_start,
        window_end=row.window_end,
        confidence=row.confidence,
        evidence=dict(row.evidence),
        explanation=_explanation(row.explanation),
        model_version=row.model_version,
        is_fallback=row.is_fallback,
        fallback_reason=row.fallback_reason,
        generated_at=row.generated_at,
    )


def _dropout(row: RiskAssessmentOrm, name: str) -> DropoutRiskView:
    return DropoutRiskView(
        patient_id=row.patient_id,
        patient_name=name,
        risk_tier=None if row.risk_tier is None else RiskTier(row.risk_tier),
        explanation=_explanation(row.explanation),
        is_fallback=row.is_fallback,
        fallback_reason=row.fallback_reason,
        generated_at=row.generated_at,
    )


def _summary(row: ClinicalSummaryOrm) -> ClinicalSummaryView:
    sections_raw = dict(row.sections)
    items: Sequence[Mapping[str, Any]] = sections_raw.get("items", [])
    return ClinicalSummaryView(
        summary_id=row.id,
        patient_id=row.patient_id,
        period_start=row.period_start,
        period_end=row.period_end,
        summary_text=str(sections_raw.get("summary_text", "")),
        sections=tuple(
            SummarySection(
                title=str(item["title"]),
                text=str(item["text"]),
                refs=tuple(str(ref) for ref in item.get("refs", [])),
            )
            for item in items
        ),
        numeric_check_matched=row.numeric_check_matched,
        model_version=row.model_version,
        is_fallback=row.is_fallback,
        fallback_reason=row.fallback_reason,
        generated_at=row.generated_at,
    )


def _evaluation(row: AiEvaluationOrm) -> AiEvaluationView:
    return AiEvaluationView(
        evaluation_id=row.id,
        use_case=row.use_case,
        model_name=row.model_name,
        model_version=row.model_version,
        baseline_name=row.baseline_name,
        cohort_ref=row.cohort_ref,
        sample_size=row.sample_size,
        model_metrics=dict(row.model_metrics),
        baseline_metrics=dict(row.baseline_metrics),
        fallback_usage_pct=row.fallback_usage_pct,
        evaluated_at=row.evaluated_at,
    )
