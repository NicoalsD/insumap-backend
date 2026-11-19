"""Strict models of the insumap-ai responses (Contrato-IA 4.3 and 8.1).

Unknown response fields are ignored, as the contract allows. Everything the
backend uses is checked: finite numbers, ordered quantiles, probabilities in
``[0, 1]``, known enums and the fallback reason that matches ``is_fallback``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insumap.application.ai.assessments import EscalationLevel
from insumap.application.metrics.forecast import FallbackReason
from insumap.domain.ai.linear_fallback import Trend
from insumap.domain.ai.risk import RiskTier
from insumap.shared.field_limits import FieldLimits


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class FactorModel(_Model):
    name: str
    direction: str
    value: float | str | None = None
    unit: str | None = None
    contribution: float = Field(ge=0, le=1, allow_inf_nan=False)


class DataRefModel(_Model):
    kind: str
    from_: datetime = Field(alias="from")
    to: datetime
    count: int = Field(ge=0)


class ExplanationModel(_Model):
    summary: str = Field(max_length=FieldLimits.AI_SUMMARY_MAX_LENGTH)
    factors: list[FactorModel] = Field(default_factory=list)
    data_refs: list[DataRefModel] = Field(default_factory=list)


class ForecastPointModel(_Model):
    horizon_minutes: int = Field(ge=1)
    timestamp: datetime
    p10: float = Field(allow_inf_nan=False)
    p50: float = Field(allow_inf_nan=False)
    p90: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def quantiles_are_ordered(self) -> Self:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("quantiles must satisfy p10 <= p50 <= p90")
        return self


class ProbabilityModel(_Model):
    horizon_minutes: int = Field(ge=1)
    probability: float = Field(ge=0, le=1, allow_inf_nan=False)


class RiskModel(_Model):
    hypo_probability: list[ProbabilityModel] = Field(default_factory=list)
    hyper_probability: list[ProbabilityModel] = Field(default_factory=list)


class GlucoseForecastResponse(_Model):
    model_name: str = Field(min_length=1, max_length=80)
    model_version: str = Field(min_length=1, max_length=80)
    input_hash: str = Field(
        min_length=FieldLimits.AI_HASH_LENGTH, max_length=FieldLimits.AI_HASH_LENGTH
    )
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None = None
    trend: Trend | None = None
    points: list[ForecastPointModel] = Field(default_factory=list)
    risk: RiskModel = Field(default_factory=RiskModel)
    explanation: ExplanationModel

    @model_validator(mode="after")
    def fallback_reason_matches_flag(self) -> Self:
        if self.is_fallback != (self.fallback_reason is not None):
            raise ValueError("is_fallback and fallback_reason disagree")
        return self


class _OutputModel(_Model):
    """The common fields of every ``200`` (Contrato-IA 4.3) and their consistency."""

    model_name: str = Field(min_length=1, max_length=80)
    model_version: str = Field(min_length=1, max_length=80)
    input_hash: str = Field(
        min_length=FieldLimits.AI_HASH_LENGTH, max_length=FieldLimits.AI_HASH_LENGTH
    )
    generated_at: datetime
    is_fallback: bool
    fallback_reason: FallbackReason | None = None
    explanation: ExplanationModel

    @model_validator(mode="after")
    def fallback_reason_matches_flag(self) -> Self:
        if self.is_fallback != (self.fallback_reason is not None):
            raise ValueError("is_fallback and fallback_reason disagree")
        return self


class RiskAssessmentResponse(_OutputModel):
    """``POST /v1/risk-assessments`` (IA2): the probability and the tier, if any."""

    assessment_type: str = Field(pattern="^(DETERIORATION|DROPOUT)$")
    risk_probability: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    calibrated: bool
    risk_tier: RiskTier | None = None


class SummarySectionModel(_Model):
    title: str = Field(min_length=1, max_length=FieldLimits.AI_SUMMARY_TEXT_MAX_LENGTH)
    text: str = Field(min_length=1, max_length=FieldLimits.AI_SUMMARY_TEXT_MAX_LENGTH)
    refs: list[str] = Field(default_factory=list)


class NumericCheckModel(_Model):
    all_matched: bool


class ClinicalSummaryResponse(_OutputModel):
    """``POST /v1/clinical-summaries`` (IA5): the text, its sections and the check."""

    summary_text: str = Field(
        min_length=1, max_length=FieldLimits.AI_SUMMARY_TEXT_MAX_LENGTH
    )
    sections: list[SummarySectionModel] = Field(default_factory=list)
    numeric_check: NumericCheckModel


class EscalationModel(_Model):
    level: EscalationLevel
    message: str | None = Field(
        default=None, max_length=FieldLimits.AI_SUMMARY_TEXT_MAX_LENGTH
    )


class AssistantReplyResponse(_OutputModel):
    """``POST /v1/assistant-replies`` (IA6): a reply no longer than the stored
    column."""

    reply_text: str = Field(
        min_length=1, max_length=FieldLimits.AI_ASSISTANT_MESSAGE_MAX_LENGTH
    )
    citations: list[str] = Field(default_factory=list)
    escalation: EscalationModel
    guardrails_triggered: list[str] = Field(default_factory=list)
