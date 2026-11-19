"""Persists AI outputs and their audit rows in a system transaction (P09 over P11)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, final, override

from sqlalchemy import text

from insumap.application.ai.assessments import (
    AiExplanation,
    AssistantResult,
    SummaryResult,
)
from insumap.application.ai.ports import (
    AiOutputStorePort,
    AssistantRecord,
    ForecastRecord,
    RiskRecord,
    SummaryRecord,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionContext,
    TransactionFactory,
)
from insumap.infrastructure.persistence.orm import (
    AssistantMessageOrm,
    ClinicalSummaryOrm,
    GlucoseForecastOrm,
    RiskAssessmentOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

SYSTEM_ACCESS_LOG: Final = text(
    "INSERT INTO audit.data_access_log (clinic_id, patient_id, actor_user_id,"
    " actor_role, actor_type, resource_type, action, outcome, purpose, request_id,"
    " occurred_at)"
    " VALUES (:clinic_id,"
    " (SELECT p.id FROM clinic.patients AS p WHERE p.id = :patient_id),"
    " NULL, NULL, 'SYSTEM', 'AI_OUTPUTS', 'READ', 'GRANTED', 'AI_PROCESSING',"
    " :request_id, :occurred_at)"
)
"""The actor is the system: no user and no role, only the purpose of the read."""


@final
class SqlAiOutputStore(AiOutputStorePort):
    """One transaction in the system context writes the output and its audit row."""

    def __init__(
        self,
        current: CurrentSession,
        transactions: TransactionFactory,
        ids: IdGenerator,
    ) -> None:
        self._current = current
        self._transactions = transactions
        self._ids = ids

    @override
    def store_forecast(
        self, record: ForecastRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        output = record.output
        with self._transactions.open() as transaction:
            transaction.apply_context(TransactionContext.for_system(record.clinic_id))
            session = self._current.get()
            session.add(
                GlucoseForecastOrm(
                    id=self._ids.new_id(),
                    clinic_id=record.clinic_id,
                    patient_id=record.patient_id,
                    mode=record.mode.value,
                    based_on_reading_id=None,
                    points=[_point(point) for point in output.points],
                    hypo_probability=[
                        _risk(r.horizon_minutes, r.hypo_probability)
                        for r in output.risk
                    ],
                    hyper_probability=[
                        _risk(r.horizon_minutes, r.hyper_probability)
                        for r in output.risk
                    ],
                    target_profile_id=record.target_profile_id,
                    model_name=output.model_name,
                    model_version=output.model_version,
                    input_hash=output.input_hash,
                    explanation=_explanation(output),
                    is_fallback=output.is_fallback,
                    fallback_reason=None
                    if output.fallback_reason is None
                    else output.fallback_reason.value,
                    is_shadow=False,
                    generated_at=output.generated_at,
                    created_at=output.generated_at,
                )
            )
            session.execute(
                SYSTEM_ACCESS_LOG,
                {
                    "clinic_id": record.clinic_id,
                    "patient_id": record.patient_id,
                    "request_id": request_id,
                    "occurred_at": occurred_at,
                },
            )
            transaction.commit()

    @override
    def store_risk(
        self, record: RiskRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        output = record.output
        with self._transactions.open() as transaction:
            transaction.apply_context(TransactionContext.for_system(record.clinic_id))
            session = self._current.get()
            session.add(
                RiskAssessmentOrm(
                    id=self._ids.new_id(),
                    clinic_id=record.clinic_id,
                    patient_id=record.patient_id,
                    assessment_type="DETERIORATION",
                    risk_probability=output.risk_probability,
                    risk_tier=None
                    if output.risk_tier is None
                    else output.risk_tier.value,
                    calibrated=output.calibrated,
                    window_days=record.window_days,
                    metric_snapshot_id=None,
                    target_profile_id=record.target_profile_id,
                    model_name=output.model_name,
                    model_version=output.model_version,
                    input_hash=output.input_hash,
                    explanation=_ai_explanation(output.explanation),
                    is_fallback=output.is_fallback,
                    fallback_reason=_reason(output.fallback_reason),
                    is_shadow=False,
                    generated_at=output.generated_at,
                    created_at=output.generated_at,
                )
            )
            session.execute(
                SYSTEM_ACCESS_LOG,
                {
                    "clinic_id": record.clinic_id,
                    "patient_id": record.patient_id,
                    "request_id": request_id,
                    "occurred_at": occurred_at,
                },
            )
            transaction.commit()

    @override
    def store_summary(
        self, record: SummaryRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        output: SummaryResult = record.output
        with self._transactions.open() as transaction:
            transaction.apply_context(TransactionContext.for_system(record.clinic_id))
            session = self._current.get()
            session.add(
                ClinicalSummaryOrm(
                    id=output.summary_id,
                    clinic_id=record.clinic_id,
                    patient_id=record.patient_id,
                    period_start=output.period_start,
                    period_end=output.period_end,
                    sections=_sections(output),
                    numeric_check_matched=output.numeric_check_matched,
                    requested_by=record.requested_by,
                    model_name=output.model_name,
                    model_version=output.model_version,
                    input_hash=output.input_hash,
                    explanation=_ai_explanation(output.explanation),
                    is_fallback=output.is_fallback,
                    fallback_reason=_reason(output.fallback_reason),
                    is_shadow=False,
                    generated_at=output.generated_at,
                    created_at=output.generated_at,
                )
            )
            session.execute(
                SYSTEM_ACCESS_LOG,
                {
                    "clinic_id": record.clinic_id,
                    "patient_id": record.patient_id,
                    "request_id": request_id,
                    "occurred_at": occurred_at,
                },
            )
            transaction.commit()

    @override
    def store_assistant_reply(
        self, record: AssistantRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        output: AssistantResult = record.output
        with self._transactions.open() as transaction:
            transaction.apply_context(TransactionContext.for_system(record.clinic_id))
            session = self._current.get()
            session.add(
                AssistantMessageOrm(
                    id=record.reply_id,
                    clinic_id=record.clinic_id,
                    patient_id=record.patient_id,
                    conversation_id=output.conversation_id,
                    sender="ASSISTANT",
                    content=output.reply_text,
                    escalation_level=output.escalation.value,
                    guardrails_triggered=list(output.guardrails_triggered),
                    context_doc_ids=list(record.context_doc_ids),
                    external_consent_id=record.external_consent_id,
                    model_name=output.model_name,
                    model_version=output.model_version,
                    input_hash=output.input_hash,
                    explanation=None
                    if output.explanation is None
                    else _ai_explanation(output.explanation),
                    is_fallback=output.is_fallback,
                    fallback_reason=_reason(output.fallback_reason),
                    sent_at=output.generated_at,
                )
            )
            session.execute(
                SYSTEM_ACCESS_LOG,
                {
                    "clinic_id": record.clinic_id,
                    "patient_id": record.patient_id,
                    "request_id": request_id,
                    "occurred_at": occurred_at,
                },
            )
            transaction.commit()


def _ai_explanation(explanation: AiExplanation | None) -> dict[str, Any]:
    if explanation is None:
        return {"summary": "", "factors": [], "data_refs": []}
    return {
        "summary": explanation.summary,
        "factors": [dict(item) for item in explanation.factors],
        "data_refs": [dict(item) for item in explanation.data_refs],
    }


def _sections(output: SummaryResult) -> dict[str, Any]:
    """``sections`` must be a JSON object (CHECK), so the list is wrapped."""
    return {
        "summary_text": output.summary_text,
        "items": [
            {"title": item.title, "text": item.text, "refs": list(item.refs)}
            for item in output.sections
        ],
    }


def _reason(value: Any) -> str | None:
    return None if value is None else value.value


def _point(point: Any) -> dict[str, Any]:
    return {
        "horizon_minutes": point.horizon_minutes,
        "timestamp": point.timestamp.isoformat(),
        "p10": float(point.p10),
        "p50": float(point.p50),
        "p90": float(point.p90),
    }


def _risk(horizon: int, probability: Any) -> dict[str, Any]:
    return {"horizon_minutes": horizon, "probability": float(probability)}


def _explanation(output: Any) -> dict[str, Any]:
    explanation = output.explanation
    return {
        "summary": "" if explanation is None else explanation.summary,
        "factors": [] if explanation is None else list(explanation.factors),
        "data_refs": [] if explanation is None else list(explanation.data_refs),
    }
