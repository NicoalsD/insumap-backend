"""``RemoteAiServiceProxy``: the service, the circuit breaker and the rule fallbacks.

Pattern: P11 Proxy. It protects the service from a failing client (P18 breaker)
and the reader from a failing service: every capability answers ``200``, from the
service or from its fallback (rules for IA2, the template for IA5, the predefined
text for IA6, the linear extrapolation for IA1). Every output is stored with its
audit row (``AI_PROCESSING``), whatever its source.

Minimization: each request is built here field by field. No name, document,
contact or patient id leaves this class; only ``subject_ref``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, time
from typing import Final, final, override
from uuid import UUID

from insumap.application.ai.assessments import (
    AiExplanation,
    AssistantPort,
    AssistantRequest,
    AssistantResult,
    ClinicalSummaryPort,
    EscalationLevel,
    RiskAssessmentPort,
    RiskRequest,
    RiskResult,
    SummaryRequest,
    SummaryResult,
    SummarySection,
)
from insumap.application.ai.ports import (
    AiCallError,
    AiOutputStorePort,
    AiServicePort,
    AssistantCall,
    AssistantRecord,
    ForecastCall,
    ForecastRecord,
    RemoteAssistant,
    RemoteForecast,
    RemoteRisk,
    RemoteSummary,
    RiskCall,
    RiskRecord,
    SummaryCall,
    SummaryRecord,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.metrics.forecast import (
    FallbackReason,
    ForecastExplanation,
    ForecastMode,
    ForecastPoint,
    ForecastRequest,
    ForecastRisk,
    GlucoseForecast,
    GlucoseForecastPort,
)
from insumap.domain.ai.circuit_breaker import CircuitBreaker
from insumap.domain.ai.linear_fallback import (
    FALLBACK_MODEL_NAME,
    FALLBACK_MODEL_VERSION,
    LinearForecastResult,
    linear_forecast,
)
from insumap.domain.ai.risk import FactorDirection, RiskScore, RiskScoringStrategy
from insumap.domain.ai.summary_template import (
    SummaryNumbers,
    SummaryTemplate,
    build_summary_template,
)
from insumap.infrastructure.ai.pseudonymizer import HmacPseudonymizer
from insumap.infrastructure.ai.wire import (
    canonical_hash,
    contract_diabetes_type,
    forecast_body,
    risk_body,
    summary_body,
)
from insumap.shared.field_limits import FieldLimits
from insumap.shared.i18n.message_catalog import MessageCatalog
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock

SHORT_TERM_HORIZONS: Final[tuple[int, ...]] = (30, 60, 120)
"""Horizons of IA1 in minutes (Modulo-IA 6.1), a product choice, not a target."""
CGM_INTERVAL_MINUTES: Final = 5
"""Nominal sensor interval sent to the service; gaps are sent as they are."""
QUANTILE_LEVELS: Final[tuple[float, ...]] = (0.1, 0.5, 0.9)
INSUFFICIENT_SUMMARY: Final = "Datos insuficientes para calcular un pronóstico."
FALLBACK_FACTORS: Final[tuple[str, ...]] = ("recent_slope", "latest_value")
RULES_MODEL_NAME: Final = "risk-rules"
RULES_MODEL_VERSION: Final = "risk-rules@1.0.0"
TEMPLATE_MODEL_NAME: Final = "summary-template"
TEMPLATE_MODEL_VERSION: Final = "summary-template@1.0.0"
ASSISTANT_FALLBACK_TEXT: Final = "ai.assistant.fallback_reply"
SUMMARY_INSUFFICIENT_TEXT: Final = "ai.summary.insufficient"
RISK_INSUFFICIENT_TEXT: Final = "ai.risk.insufficient"
RISK_RULES_TEXT: Final = "ai.risk.rules_summary"
LABEL_TEMPLATE: Final = "ai.summary.template.label"


@final
class RemoteAiServiceProxy(
    GlucoseForecastPort, RiskAssessmentPort, ClinicalSummaryPort, AssistantPort
):
    """Calls the service through the breaker and answers with the fallback when it
    cannot.

    Pattern: P11 Proxy
    """

    def __init__(
        self,
        *,
        service: AiServicePort | None,
        breaker: CircuitBreaker,
        enabled: bool,
        pseudonymizer: HmacPseudonymizer,
        store: AiOutputStorePort,
        clock: Clock,
        ids: IdGenerator,
        risk_strategy: RiskScoringStrategy,
        messages: MessageCatalog,
        horizons_minutes: tuple[int, ...] = SHORT_TERM_HORIZONS,
    ) -> None:
        self._service = service
        self._breaker = breaker
        self._enabled = enabled
        self._pseudonymizer = pseudonymizer
        self._store = store
        self._clock = clock
        self._ids = ids
        self._strategy = risk_strategy
        self._messages = messages
        self._horizons = horizons_minutes
        self._lock = threading.Lock()

    # IA1: glucose forecast (P11 over the linear fallback).

    @override
    def forecast(self, request: ForecastRequest) -> GlucoseForecast:
        call = self._minimized_call(request)
        output = self._answer(request, call)
        self._store.store_forecast(
            ForecastRecord(
                clinic_id=request.clinic_id,
                patient_id=request.patient_id,
                target_profile_id=request.target_profile_id,
                mode=request.mode,
                output=output,
            ),
            request_id=current_request_id(),
            occurred_at=self._clock.now(),
        )
        return _as_forecast(output, request.mode)

    def _answer(self, request: ForecastRequest, call: ForecastCall) -> RemoteForecast:
        answer, reason = self._remote(lambda service: service.glucose_forecast(call))
        if answer is not None:
            return answer
        return self._fallback(request, call, reason or FallbackReason.AI_ERROR)

    def _minimized_call(self, request: ForecastRequest) -> ForecastCall:
        series = request.series[-FieldLimits.AI_MAX_FORECAST_POINTS :]
        return ForecastCall(
            subject_ref=self._pseudonymizer.subject_ref(request.patient_id).value,
            mode=request.mode,
            timestamps=tuple(point.at for point in series),
            values_mg_dl=tuple(point.mg_dl for point in series),
            interval_minutes=CGM_INTERVAL_MINUTES,
            horizons_minutes=self._horizons,
            quantile_levels=QUANTILE_LEVELS,
            low_mg_dl=request.low_mg_dl,
            high_mg_dl=request.high_mg_dl,
            clinic_timezone=request.timezone,
            night_start=_hhmm(request.night_start),
            night_end=_hhmm(request.night_end),
        )

    def _fallback(
        self, request: ForecastRequest, call: ForecastCall, reason: FallbackReason
    ) -> RemoteForecast:
        digest = canonical_hash(forecast_body(call))
        now = self._clock.now()
        result = linear_forecast(
            request.series,
            horizons_minutes=self._horizons,
            low_mg_dl=request.low_mg_dl,
            high_mg_dl=request.high_mg_dl,
        )
        if result is None:
            return _insufficient(digest, now)
        return _linear(result, digest, now, reason)

    # IA2: risk of deterioration (P19 strategy over P11).

    @override
    def assess(self, request: RiskRequest) -> RiskResult:
        output = self._risk_output(request)
        self._store.store_risk(
            RiskRecord(
                clinic_id=request.clinic_id,
                patient_id=request.patient_id,
                target_profile_id=request.target_profile_id,
                window_days=request.window_days,
                output=output,
            ),
            request_id=current_request_id(),
            occurred_at=self._clock.now(),
        )
        return output

    def _risk_output(self, request: RiskRequest) -> RiskResult:
        if not request.is_sufficient:
            return self._insufficient_risk(request, self._risk_digest(request))
        contract = contract_diabetes_type(request.diabetes_type)
        if contract is None:
            return self._rules_risk(request, FallbackReason.AI_ERROR)
        call = RiskCall(
            subject_ref=self._subject_ref(request.patient_id),
            window_days=request.window_days,
            diabetes_type=contract,
            target_tir_pct=request.limits.tir_min_pct,
            features=request.features,
        )
        answer, reason = self._remote(lambda service: service.risk_assessment(call))
        if answer is not None:
            return _risk_from(answer, request.window_days)
        return self._rules_risk(request, reason or FallbackReason.AI_ERROR)

    def _rules_risk(self, request: RiskRequest, reason: FallbackReason) -> RiskResult:
        score = self._strategy.score(request.features, request.limits)
        digest = self._risk_digest(request)
        if not score.is_sufficient:
            return self._insufficient_risk(request, digest)
        return RiskResult(
            model_name=RULES_MODEL_NAME,
            model_version=RULES_MODEL_VERSION,
            input_hash=digest,
            generated_at=self._clock.now(),
            is_fallback=True,
            fallback_reason=reason,
            risk_probability=score.probability,
            risk_tier=score.tier,
            calibrated=False,
            window_days=request.window_days,
            explanation=AiExplanation(
                summary=self._messages.render(
                    RISK_RULES_TEXT,
                    breaches=score.breaches,
                    evaluated=score.evaluated,
                    days=request.window_days,
                ),
                factors=_factor_maps(score),
                data_refs=(),
            ),
        )

    def _insufficient_risk(self, request: RiskRequest, digest: str) -> RiskResult:
        sufficiency = request.features.data_sufficiency_pct
        return RiskResult(
            model_name=RULES_MODEL_NAME,
            model_version=RULES_MODEL_VERSION,
            input_hash=digest,
            generated_at=self._clock.now(),
            is_fallback=True,
            fallback_reason=FallbackReason.INSUFFICIENT_DATA,
            risk_probability=None,
            risk_tier=None,
            calibrated=False,
            window_days=request.window_days,
            explanation=AiExplanation(
                summary=self._messages.render(RISK_INSUFFICIENT_TEXT),
                factors=(
                    {
                        "name": "data_sufficiency_pct",
                        "direction": FactorDirection.NEUTRAL.value,
                        "value": 0.0 if sufficiency is None else float(sufficiency),
                        "unit": "%",
                        "contribution": 0.0,
                    },
                ),
            ),
        )

    def _risk_digest(self, request: RiskRequest) -> str:
        """The hash of the input the rules read, as the contract hashes a body."""
        return canonical_hash(
            risk_body(
                RiskCall(
                    subject_ref=self._subject_ref(request.patient_id),
                    window_days=request.window_days,
                    diabetes_type=request.diabetes_type,
                    target_tir_pct=request.limits.tir_min_pct,
                    features=request.features,
                )
            )
        )

    # IA5: pre-visit summary (P11 over the template).

    @override
    def summarize(self, request: SummaryRequest) -> SummaryResult:
        summary_id = self._ids.new_id()
        numbers = SummaryNumbers(
            tir_pct=request.metrics.tir_pct,
            target_tir_pct=request.target_tir_pct,
            gmi_pct=request.metrics.gmi_pct,
            hypo_events_count=request.metrics.hypo_events_count,
            readings_per_day=request.readings_per_day,
        )
        template = build_summary_template(numbers) if request.is_sufficient else None
        call = self._summary_call(request)
        result = self._summary_output(request, summary_id, call, template)
        self._store.store_summary(
            SummaryRecord(
                clinic_id=request.clinic_id,
                patient_id=request.patient_id,
                requested_by=request.requested_by,
                output=result,
            ),
            request_id=current_request_id(),
            occurred_at=self._clock.now(),
        )
        return result

    def _summary_output(
        self,
        request: SummaryRequest,
        summary_id: UUID,
        call: SummaryCall,
        template: SummaryTemplate | None,
    ) -> SummaryResult:
        if template is None:
            return self._template_summary(
                request, summary_id, call, None, FallbackReason.INSUFFICIENT_DATA
            )
        if not request.use_llm:
            # Policy, not failure: a non demo clinic without LLM_REAL_DATA_ALLOWED.
            return self._template_summary(
                request, summary_id, call, template, FallbackReason.CIRCUIT_OPEN
            )
        contract = contract_diabetes_type(request.diabetes_type)
        if contract is None:
            return self._template_summary(
                request, summary_id, call, template, FallbackReason.AI_ERROR
            )
        answer, reason = self._remote(lambda service: service.clinical_summary(call))
        if answer is not None and answer.numeric_all_matched:
            return _summary_from(answer, summary_id, request)
        if answer is not None:
            # The numbers do not match the input: the text is discarded (Contrato 8.5).
            reason = FallbackReason.AI_ERROR
        return self._template_summary(
            request, summary_id, call, template, reason or FallbackReason.AI_ERROR
        )

    def _template_summary(
        self,
        request: SummaryRequest,
        summary_id: UUID,
        call: SummaryCall,
        template: SummaryTemplate | None,
        reason: FallbackReason,
    ) -> SummaryResult:
        now = self._clock.now()
        digest = canonical_hash(summary_body(call))
        if template is None:
            return SummaryResult(
                summary_id=summary_id,
                period_start=request.period_start,
                period_end=request.period_end,
                model_name=TEMPLATE_MODEL_NAME,
                model_version=TEMPLATE_MODEL_VERSION,
                input_hash=digest,
                generated_at=now,
                is_fallback=True,
                fallback_reason=reason,
                summary_text=self._messages.render(SUMMARY_INSUFFICIENT_TEXT),
                sections=(),
                numeric_check_matched=True,
                explanation=AiExplanation(
                    summary=self._messages.render(LABEL_TEMPLATE)
                ),
            )
        sections = tuple(
            SummarySection(
                title=self._messages.render(f"{section.key}.title"),
                text=self._messages.render(f"{section.key}.text", **section.params),
                refs=section.refs,
            )
            for section in template.sections
        )
        return SummaryResult(
            summary_id=summary_id,
            period_start=request.period_start,
            period_end=request.period_end,
            model_name=TEMPLATE_MODEL_NAME,
            model_version=TEMPLATE_MODEL_VERSION,
            input_hash=digest,
            generated_at=now,
            is_fallback=True,
            fallback_reason=reason,
            summary_text=" ".join(section.text for section in sections),
            sections=sections,
            numeric_check_matched=True,
            explanation=AiExplanation(summary=self._messages.render(LABEL_TEMPLATE)),
        )

    def _summary_call(self, request: SummaryRequest) -> SummaryCall:
        return SummaryCall(
            subject_ref=self._subject_ref(request.patient_id),
            period_start=request.period_start,
            period_end=request.period_end,
            diabetes_type=request.diabetes_type,
            metrics=request.metrics,
            target_tir_pct=request.target_tir_pct,
            readings_per_day=request.readings_per_day,
        )

    # IA6: assistant reply (P11 over the predefined text).

    @override
    def reply(self, request: AssistantRequest) -> AssistantResult:
        reply_id = self._ids.new_id()
        if request.external_consent_id is None:
            # Without the external processing consent no call is made (API.md 8.10).
            result = self._predefined(request, FallbackReason.CIRCUIT_OPEN)
        else:
            call = AssistantCall(
                subject_ref=self._subject_ref(request.patient_id),
                message=request.message,
                history=request.history,
                fragments=request.fragments,
            )
            answer, reason = self._remote(lambda service: service.assistant_reply(call))
            if answer is not None:
                result = _reply_from(answer, request)
            else:
                result = self._predefined(request, reason or FallbackReason.AI_ERROR)
        self._store.store_assistant_reply(
            AssistantRecord(
                reply_id=reply_id,
                clinic_id=request.clinic_id,
                patient_id=request.patient_id,
                output=result,
                context_doc_ids=tuple(
                    fragment.doc_id for fragment in request.fragments
                ),
                external_consent_id=request.external_consent_id,
            ),
            request_id=current_request_id(),
            occurred_at=self._clock.now(),
        )
        return result

    def _predefined(
        self, request: AssistantRequest, reason: FallbackReason
    ) -> AssistantResult:
        return AssistantResult(
            conversation_id=request.conversation_id,
            reply_text=self._messages.render(ASSISTANT_FALLBACK_TEXT),
            citations=(),
            escalation=EscalationLevel.NONE,
            escalation_message=None,
            guardrails_triggered=(),
            model_name=None,
            model_version=None,
            input_hash=None,
            explanation=None,
            is_fallback=True,
            fallback_reason=reason,
            generated_at=self._clock.now(),
        )

    # Shared: the breaker and the call, once for every capability (P18).

    def _remote[T](
        self, send: Callable[[AiServicePort], T]
    ) -> tuple[T | None, FallbackReason | None]:
        """The answer, or the reason the service did not give one. Counts the
        breaker."""
        if not self._enabled:
            return None, FallbackReason.CIRCUIT_OPEN
        if self._service is None:
            return None, FallbackReason.AI_ERROR
        now = self._clock.now()
        with self._lock:
            allowed = self._breaker.allow(now)
        if not allowed:
            return None, FallbackReason.CIRCUIT_OPEN
        try:
            answer = send(self._service)
        except AiCallError as error:
            with self._lock:
                # A 413 or 422 proves the service is alive: the backend sent a bad body.
                if error.counts_as_failure:
                    self._breaker.record_failure(now)
                else:
                    self._breaker.record_success(now)
            return None, error.reason
        with self._lock:
            self._breaker.record_success(now)
        return answer, None

    def _subject_ref(self, patient_id: UUID) -> str:
        return self._pseudonymizer.subject_ref(patient_id).value


def _hhmm(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _linear(
    result: LinearForecastResult, digest: str, now: datetime, reason: FallbackReason
) -> RemoteForecast:
    return RemoteForecast(
        model_name=FALLBACK_MODEL_NAME,
        model_version=FALLBACK_MODEL_VERSION,
        input_hash=digest,
        generated_at=now,
        is_fallback=True,
        fallback_reason=reason,
        trend=result.trend,
        points=tuple(
            ForecastPoint(
                horizon_minutes=point.horizon_minutes,
                timestamp=point.timestamp,
                p10=point.p10,
                p50=point.p50,
                p90=point.p90,
            )
            for point in result.points
        ),
        risk=tuple(
            ForecastRisk(
                horizon_minutes=point.horizon_minutes,
                hypo_probability=point.hypo_probability,
                hyper_probability=point.hyper_probability,
            )
            for point in result.points
        ),
        explanation=ForecastExplanation(
            summary=result.summary,
            factors=FALLBACK_FACTORS,
            data_refs=(),
        ),
    )


def _insufficient(digest: str, now: datetime) -> RemoteForecast:
    return RemoteForecast(
        model_name=FALLBACK_MODEL_NAME,
        model_version=FALLBACK_MODEL_VERSION,
        input_hash=digest,
        generated_at=now,
        is_fallback=True,
        fallback_reason=FallbackReason.INSUFFICIENT_DATA,
        trend=None,
        points=(),
        risk=(),
        explanation=ForecastExplanation(
            summary=INSUFFICIENT_SUMMARY, factors=(), data_refs=()
        ),
    )


def _as_forecast(output: RemoteForecast, mode: ForecastMode) -> GlucoseForecast:
    return GlucoseForecast(
        mode=mode,
        generated_at=output.generated_at,
        model_name=output.model_name,
        model_version=output.model_version,
        is_fallback=output.is_fallback,
        fallback_reason=output.fallback_reason,
        trend=output.trend,
        points=output.points,
        risk=output.risk,
        explanation=output.explanation,
    )


def _risk_from(answer: RemoteRisk, window_days: int) -> RiskResult:
    return RiskResult(
        model_name=answer.model_name,
        model_version=answer.model_version,
        input_hash=answer.input_hash,
        generated_at=answer.generated_at,
        is_fallback=answer.is_fallback,
        fallback_reason=answer.fallback_reason,
        risk_probability=answer.risk_probability,
        risk_tier=answer.risk_tier,
        calibrated=answer.calibrated,
        window_days=window_days,
        explanation=answer.explanation,
    )


def _summary_from(
    answer: RemoteSummary, summary_id: UUID, request: SummaryRequest
) -> SummaryResult:
    return SummaryResult(
        summary_id=summary_id,
        period_start=request.period_start,
        period_end=request.period_end,
        model_name=answer.model_name,
        model_version=answer.model_version,
        input_hash=answer.input_hash,
        generated_at=answer.generated_at,
        is_fallback=answer.is_fallback,
        fallback_reason=answer.fallback_reason,
        summary_text=answer.summary_text,
        sections=answer.sections,
        numeric_check_matched=answer.numeric_all_matched,
        explanation=answer.explanation,
    )


def _reply_from(answer: RemoteAssistant, request: AssistantRequest) -> AssistantResult:
    """Keeps only the citations of material that was sent (the service may echo
    more)."""
    sent = {str(fragment.doc_id): fragment for fragment in request.fragments}
    citations = tuple(
        sent[doc_id].doc_id for doc_id in answer.citations if doc_id in sent
    )
    return AssistantResult(
        conversation_id=request.conversation_id,
        reply_text=answer.reply_text,
        citations=citations,
        escalation=answer.escalation,
        escalation_message=answer.escalation_message,
        guardrails_triggered=answer.guardrails_triggered,
        model_name=answer.model_name,
        model_version=answer.model_version,
        input_hash=answer.input_hash,
        explanation=answer.explanation,
        is_fallback=answer.is_fallback,
        fallback_reason=answer.fallback_reason,
        generated_at=answer.generated_at,
    )


def _factor_maps(score: RiskScore) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "name": factor.name,
            "direction": factor.direction.value,
            "value": float(factor.value),
            "unit": factor.unit,
            "contribution": float(factor.contribution),
        }
        for factor in score.factors
    )
