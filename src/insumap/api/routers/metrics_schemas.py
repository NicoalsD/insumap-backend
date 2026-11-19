"""Response models of the glycemic metrics, AGP and forecast endpoints (API.md 8.8)."""

from datetime import datetime
from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import BaseModel, Field

from insumap.application.metrics.forecast import (
    FallbackReason,
    ForecastMode,
    GlucoseForecast,
)
from insumap.application.metrics.metrics import (
    AgpResult,
    MetricsResult,
    MetricWindow,
)
from insumap.domain.ai.linear_fallback import Trend
from insumap.domain.metrics.glycemic_metrics import Confidence, GlycemicMetrics
from insumap.domain.metrics.target_profile import TargetProfile


def _number(value: Decimal | None) -> float | None:
    """Decimals leave the API as numbers, as the records endpoints do."""
    return None if value is None else float(value)


class TargetThresholds(BaseModel):
    """Cut points and goals of a profile; the screens draw their ranges from them."""

    population: str
    range_low_mg_dl: float
    range_high_mg_dl: float
    very_low_mg_dl: float
    very_high_mg_dl: float
    tir_min_pct: float
    tbr_l1_max_pct: float
    tbr_l2_max_pct: float
    tar_l1_max_pct: float
    tar_l2_max_pct: float
    cv_max_pct: float
    min_data_sufficiency_pct: float
    min_days: int
    night_start: str
    night_end: str

    @staticmethod
    def values_of(profile: TargetProfile) -> dict[str, object]:
        return {
            "population": profile.population,
            "range_low_mg_dl": float(profile.range_low_mg_dl),
            "range_high_mg_dl": float(profile.range_high_mg_dl),
            "very_low_mg_dl": float(profile.very_low_mg_dl),
            "very_high_mg_dl": float(profile.very_high_mg_dl),
            "tir_min_pct": float(profile.tir_min_pct),
            "tbr_l1_max_pct": float(profile.tbr_l1_max_pct),
            "tbr_l2_max_pct": float(profile.tbr_l2_max_pct),
            "tar_l1_max_pct": float(profile.tar_l1_max_pct),
            "tar_l2_max_pct": float(profile.tar_l2_max_pct),
            "cv_max_pct": float(profile.cv_max_pct),
            "min_data_sufficiency_pct": float(profile.min_data_sufficiency_pct),
            "min_days": profile.min_days,
            "night_start": profile.night_start.strftime("%H:%M"),
            "night_end": profile.night_end.strftime("%H:%M"),
        }


class TargetProfileRef(TargetThresholds):
    """The profile of the targets a result was computed with."""

    id: UUID
    code: str
    version: int

    @classmethod
    def of(cls, profile: TargetProfile) -> Self:
        return cls(
            id=profile.id,
            code=profile.code,
            version=profile.version,
            **TargetThresholds.values_of(profile),  # type: ignore[arg-type]
        )


class GlycemicMetricsResponse(BaseModel):
    """The metrics of one period; `null` when the data does not allow the value."""

    tir_pct: float | None
    tbr_l1_pct: float | None
    tbr_l2_pct: float | None
    tbr_pct: float | None
    tar_l1_pct: float | None
    tar_l2_pct: float | None
    tar_pct: float | None
    mean_glucose_mg_dl: float | None
    gmi_pct: float | None
    cv_pct: float | None
    hypo_events_count: int | None

    @classmethod
    def of(cls, metrics: GlycemicMetrics) -> Self:
        return cls(
            tir_pct=_number(metrics.tir_pct),
            tbr_l1_pct=_number(metrics.tbr_l1_pct),
            tbr_l2_pct=_number(metrics.tbr_l2_pct),
            tbr_pct=_number(metrics.tbr_pct),
            tar_l1_pct=_number(metrics.tar_l1_pct),
            tar_l2_pct=_number(metrics.tar_l2_pct),
            tar_pct=_number(metrics.tar_pct),
            mean_glucose_mg_dl=_number(metrics.mean_glucose_mg_dl),
            gmi_pct=_number(metrics.gmi_pct),
            cv_pct=_number(metrics.cv_pct),
            hypo_events_count=metrics.hypo_events_count,
        )


class MetricsResponse(BaseModel):
    """The metrics of a window, with the previous one when it was asked for."""

    window: MetricWindow
    period_from: datetime
    period_to: datetime
    timezone: str
    target_profile: TargetProfileRef
    data_sufficiency_pct: float
    is_sufficient: bool = Field(
        description="Con `false` las métricas no deben mostrarse como porcentaje."
    )
    confidence: Confidence = Field(description="`NORMAL` o `LOW_CONFIDENCE`.")
    metrics: GlycemicMetricsResponse
    previous: GlycemicMetricsResponse | None = Field(
        description="Misma métrica de la ventana anterior del mismo tamaño."
    )
    tir_delta_pct: float | None = Field(
        description="Cambio del TIR frente a la ventana anterior, en puntos "
        "porcentuales y con signo."
    )

    @classmethod
    def of(cls, result: MetricsResult) -> Self:
        metrics = result.metrics
        return cls(
            window=result.window,
            period_from=result.period_from,
            period_to=result.period_to,
            timezone=result.timezone,
            target_profile=TargetProfileRef.of(result.profile),
            data_sufficiency_pct=float(metrics.data_sufficiency_pct),
            is_sufficient=metrics.is_sufficient,
            confidence=metrics.confidence,
            metrics=GlycemicMetricsResponse.of(metrics),
            previous=None
            if result.previous is None
            else GlycemicMetricsResponse.of(result.previous),
            tir_delta_pct=_number(result.tir_delta_pct),
        )


class AgpBinResponse(BaseModel):
    """Percentiles of the readings of one time of day bin, in mg/dL."""

    minute_of_day: int = Field(description="Minuto del día local en que empieza.")
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


class TargetRangeResponse(BaseModel):
    low: float
    high: float


class AgpResponse(BaseModel):
    """The ambulatory glucose profile, empty when the data is insufficient."""

    bins: list[AgpBinResponse]
    target_range: TargetRangeResponse
    data_sufficiency_pct: float
    is_sufficient: bool

    @classmethod
    def of(cls, result: AgpResult) -> Self:
        return cls(
            bins=[
                AgpBinResponse(
                    minute_of_day=item.minute_of_day,
                    p5=float(item.p5),
                    p25=float(item.p25),
                    p50=float(item.p50),
                    p75=float(item.p75),
                    p95=float(item.p95),
                )
                for item in result.bins
            ],
            target_range=TargetRangeResponse(
                low=float(result.range_low_mg_dl),
                high=float(result.range_high_mg_dl),
            ),
            data_sufficiency_pct=float(result.data_sufficiency_pct),
            is_sufficient=result.is_sufficient,
        )


class ForecastPointResponse(BaseModel):
    horizon_minutes: int
    timestamp: datetime
    p10: float
    p50: float
    p90: float


class ForecastRiskResponse(BaseModel):
    horizon_minutes: int
    hypo_probability: float
    hyper_probability: float


class ForecastExplanationResponse(BaseModel):
    summary: str
    factors: list[str]
    data_refs: list[str]


class ForecastResponse(BaseModel):
    """The short term or overnight forecast, or the rules fallback with its reason."""

    mode: ForecastMode
    generated_at: datetime
    model_name: str | None
    model_version: str | None
    is_fallback: bool = Field(description="`true` cuando responde el respaldo.")
    fallback_reason: FallbackReason | None
    trend: Trend | None
    points: list[ForecastPointResponse]
    risk: list[ForecastRiskResponse]
    explanation: ForecastExplanationResponse | None

    @classmethod
    def of(cls, forecast: GlucoseForecast) -> Self:
        return cls(
            mode=forecast.mode,
            generated_at=forecast.generated_at,
            model_name=forecast.model_name,
            model_version=forecast.model_version,
            is_fallback=forecast.is_fallback,
            fallback_reason=forecast.fallback_reason,
            trend=forecast.trend,
            points=[
                ForecastPointResponse(
                    horizon_minutes=point.horizon_minutes,
                    timestamp=point.timestamp,
                    p10=float(point.p10),
                    p50=float(point.p50),
                    p90=float(point.p90),
                )
                for point in forecast.points
            ],
            risk=[
                ForecastRiskResponse(
                    horizon_minutes=item.horizon_minutes,
                    hypo_probability=float(item.hypo_probability),
                    hyper_probability=float(item.hyper_probability),
                )
                for item in forecast.risk
            ],
            explanation=None
            if forecast.explanation is None
            else ForecastExplanationResponse(
                summary=forecast.explanation.summary,
                factors=list(forecast.explanation.factors),
                data_refs=list(forecast.explanation.data_refs),
            ),
        )
