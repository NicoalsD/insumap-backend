"""Request and response models of the AI assessments (API.md 8.10): risk, findings,
summaries.

Every response that shows AI content carries ``label``: the text tells the reader
that it is a suggestion the doctor decides on (or, for summaries, that it must be
verified against the data). ``simulated`` follows API.md 1.2.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Final, Self
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

from insumap.api.routers.common import StrictRequest
from insumap.application.ai.assessments import (
    AiExplanation,
    RiskResult,
    SummaryResult,
    SummarySection,
)
from insumap.application.ai.records import (
    AiEvaluationView,
    ClinicalSummaryView,
    DropoutRiskView,
    PatternFindingView,
)
from insumap.application.metrics.forecast import FallbackReason
from insumap.domain.ai.risk import RiskTier
from insumap.shared.field_limits import FieldLimits

RISK_LABEL_KEY: Final = "ai.suggestion.label"
SUMMARY_LABEL_KEY: Final = "ai.summary.label"
TEMPLATE_LABEL_KEY: Final = "ai.summary.template.label"
DAYS_FIELD: Final = Field(
    default=FieldLimits.AI_WINDOW_DAYS_DEFAULT,
    ge=FieldLimits.AI_WINDOW_DAYS_MIN,
    le=FieldLimits.AI_WINDOW_DAYS_MAX,
    description="Días completos de la ventana, que terminan hoy (por defecto 14).",
)


class ExplanationResponse(BaseModel):
    """What the doctor reads about an output: a sentence, its factors and its data."""

    summary: str
    factors: list[dict[str, Any]]
    data_refs: list[dict[str, Any]]

    @classmethod
    def of(cls, explanation: AiExplanation | None) -> Self:
        if explanation is None:
            return cls(summary="", factors=[], data_refs=[])
        return cls(
            summary=explanation.summary,
            factors=[dict(item) for item in explanation.factors],
            data_refs=[dict(item) for item in explanation.data_refs],
        )


class RiskResponse(BaseModel):
    """The risk of deterioration (IA2), from the service or from the rules."""

    assessment_type: str = Field(description="Siempre `DETERIORATION` en esta ruta.")
    window_days: int
    risk_probability: float | None = Field(
        description="Entre 0 y 1; `null` si los datos no alcanzan."
    )
    risk_tier: RiskTier | None
    calibrated: bool = Field(description="`false` en el respaldo por reglas.")
    explanation: ExplanationResponse
    model_version: str
    is_fallback: bool
    fallback_reason: FallbackReason | None
    generated_at: datetime
    label: str
    simulated: bool

    @classmethod
    def of(cls, result: RiskResult, *, label: str, simulated: bool) -> Self:
        return cls(
            assessment_type="DETERIORATION",
            window_days=result.window_days,
            risk_probability=None
            if result.risk_probability is None
            else float(result.risk_probability),
            risk_tier=result.risk_tier,
            calibrated=result.calibrated,
            explanation=ExplanationResponse.of(result.explanation),
            model_version=result.model_version,
            is_fallback=result.is_fallback,
            fallback_reason=result.fallback_reason,
            generated_at=result.generated_at,
            label=label,
            simulated=simulated,
        )


class DismissPatternFindingRequest(StrictRequest):
    """The doctor's note that dismisses a finding; blank notes are refused."""

    note: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=FieldLimits.PATTERN_FINDING_NOTE_MIN_LENGTH,
            max_length=FieldLimits.PATTERN_FINDING_NOTE_MAX_LENGTH,
        ),
    ] = Field(description="Nota obligatoria: por qué se descarta el hallazgo.")


class PatternFindingResponse(BaseModel):
    """One pattern or anomaly detected by IA3 (a suggestion the doctor reviews)."""

    id: UUID
    pattern_type: str
    window_start: datetime
    window_end: datetime
    confidence: float | None
    evidence: dict[str, Any]
    explanation: ExplanationResponse
    model_version: str
    is_fallback: bool
    fallback_reason: str | None
    generated_at: datetime
    status: str = Field(
        description="`DISMISSED` cuando el médico lo descartó; si no, `NEW`."
    )
    dismissed_at: datetime | None
    dismissed_by: UUID | None
    label: str
    simulated: bool

    @classmethod
    def of(cls, view: PatternFindingView, *, label: str, simulated: bool) -> Self:
        return cls(
            id=view.finding_id,
            pattern_type=view.pattern_type,
            window_start=view.window_start,
            window_end=view.window_end,
            confidence=None if view.confidence is None else float(view.confidence),
            evidence=dict(view.evidence),
            explanation=ExplanationResponse.of(view.explanation),
            model_version=view.model_version,
            is_fallback=view.is_fallback,
            fallback_reason=view.fallback_reason,
            generated_at=view.generated_at,
            status=view.status,
            dismissed_at=view.dismissed_at,
            dismissed_by=view.dismissed_by,
            label=label,
            simulated=simulated,
        )


class DropoutRiskResponse(BaseModel):
    """The dropout risk of an assigned patient: no clinical values, only the summary."""

    patient_id: UUID
    patient_name: str
    account_status: str | None = Field(
        description="Estado de la cuenta del paciente; solo en la lista del "
        "administrador, `null` para el médico."
    )
    days_without_record: int | None = Field(
        description="Días desde el último registro; `null` si nunca registró nada "
        "o si es la lista del médico."
    )
    risk_tier: RiskTier | None
    explanation: ExplanationResponse
    is_fallback: bool
    fallback_reason: str | None
    generated_at: datetime
    label: str
    simulated: bool

    @classmethod
    def of(cls, view: DropoutRiskView, *, label: str, simulated: bool) -> Self:
        return cls(
            patient_id=view.patient_id,
            patient_name=view.patient_name,
            account_status=view.account_status,
            days_without_record=view.days_without_record,
            risk_tier=view.risk_tier,
            explanation=ExplanationResponse(
                summary=view.explanation.summary, factors=[], data_refs=[]
            ),
            is_fallback=view.is_fallback,
            fallback_reason=view.fallback_reason,
            generated_at=view.generated_at,
            label=label,
            simulated=simulated,
        )


class CreateClinicalSummaryRequest(StrictRequest):
    """The window of the summary, in whole days that end today."""

    period_days: int = DAYS_FIELD


class SummarySectionResponse(BaseModel):
    title: str
    text: str
    refs: list[str]


class ClinicalSummaryResponse(BaseModel):
    """A pre-visit summary (IA5): the text, its sections and where each figure comes
    from."""

    id: UUID
    patient_id: UUID
    period_from: datetime
    period_to: datetime
    summary_text: str
    sections: list[SummarySectionResponse]
    references: list[str] = Field(
        description="Cada dato citado en las secciones, sin repetir."
    )
    numeric_check_matched: bool | None
    model_version: str
    is_fallback: bool
    fallback_reason: FallbackReason | None
    generated_at: datetime
    label: str
    simulated: bool

    @classmethod
    def of_view(cls, view: ClinicalSummaryView, *, label: str, simulated: bool) -> Self:
        return cls(
            id=view.summary_id,
            patient_id=view.patient_id,
            period_from=view.period_start,
            period_to=view.period_end,
            summary_text=view.summary_text,
            sections=[
                SummarySectionResponse(title=s.title, text=s.text, refs=list(s.refs))
                for s in view.sections
            ],
            references=_references(view.sections),
            numeric_check_matched=view.numeric_check_matched,
            model_version=view.model_version,
            is_fallback=view.is_fallback,
            fallback_reason=_reason(view.fallback_reason),
            generated_at=view.generated_at,
            label=label,
            simulated=simulated,
        )

    @classmethod
    def of_result(
        cls, result: SummaryResult, *, patient_id: UUID, label: str, simulated: bool
    ) -> Self:
        return cls(
            id=result.summary_id,
            patient_id=patient_id,
            period_from=result.period_start,
            period_to=result.period_end,
            summary_text=result.summary_text,
            sections=[
                SummarySectionResponse(title=s.title, text=s.text, refs=list(s.refs))
                for s in result.sections
            ],
            references=_references(result.sections),
            numeric_check_matched=result.numeric_check_matched,
            model_version=result.model_version,
            is_fallback=result.is_fallback,
            fallback_reason=result.fallback_reason,
            generated_at=result.generated_at,
            label=label,
            simulated=simulated,
        )


class AiEvaluationResponse(BaseModel):
    """A use case against its fallback: aggregated metrics, never patient series."""

    id: UUID
    use_case: str
    model_name: str
    model_version: str
    baseline_name: str
    cohort_ref: str
    sample_size: int
    model_metrics: dict[str, Any]
    baseline_metrics: dict[str, Any]
    fallback_usage_pct: float | None
    evaluated_at: datetime
    simulated: bool

    @classmethod
    def of(cls, view: AiEvaluationView) -> Self:
        return cls(
            id=view.evaluation_id,
            use_case=view.use_case,
            model_name=view.model_name,
            model_version=view.model_version,
            baseline_name=view.baseline_name,
            cohort_ref=view.cohort_ref,
            sample_size=view.sample_size,
            model_metrics=dict(view.model_metrics),
            baseline_metrics=dict(view.baseline_metrics),
            fallback_usage_pct=None
            if view.fallback_usage_pct is None
            else float(view.fallback_usage_pct),
            evaluated_at=view.evaluated_at,
            simulated=True,
        )


def summary_label(result: SummaryResult | ClinicalSummaryView) -> str:
    """The label key of a summary: the template says it is the fixed text."""
    return TEMPLATE_LABEL_KEY if result.is_fallback else SUMMARY_LABEL_KEY


def _references(sections: Sequence[SummarySection]) -> list[str]:
    seen: list[str] = []
    for section in sections:
        for ref in section.refs:
            if ref not in seen:
                seen.append(ref)
    return seen


def _reason(value: str | None) -> FallbackReason | None:
    return None if value is None else FallbackReason(value)
