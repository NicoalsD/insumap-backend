"""``RemoteAiServiceProxy``: the service, the circuit breaker and the rule fallback.

Pattern: P11 Proxy. It protects the service from a failing client (P18 breaker)
and the reader from a failing service (the fallback answers with ``200``). Every
output, from the service or from the fallback, is stored with its audit row.

Minimization: the request is built here field by field from the request. No name,
document, contact or patient id leaves this class; only ``subject_ref``.
"""

from __future__ import annotations

import threading
from datetime import datetime, time
from typing import Final, final, override

from insumap.application.ai.ports import (
    AiCallError,
    AiOutputStorePort,
    AiServicePort,
    ForecastCall,
    ForecastRecord,
    RemoteForecast,
)
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
from insumap.infrastructure.ai.pseudonymizer import HmacPseudonymizer
from insumap.infrastructure.ai.wire import canonical_hash, forecast_body
from insumap.shared.field_limits import FieldLimits
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock

SHORT_TERM_HORIZONS: Final[tuple[int, ...]] = (30, 60, 120)
"""Horizons of IA1 in minutes (Modulo-IA 6.1), a product choice, not a target."""
CGM_INTERVAL_MINUTES: Final = 5
"""Nominal sensor interval sent to the service; gaps are sent as they are."""
QUANTILE_LEVELS: Final[tuple[float, ...]] = (0.1, 0.5, 0.9)
INSUFFICIENT_SUMMARY: Final = "Datos insuficientes para calcular un pronóstico."
FALLBACK_FACTORS: Final[tuple[str, ...]] = ("recent_slope", "latest_value")


@final
class RemoteAiServiceProxy(GlucoseForecastPort):
    """Calls the service through the breaker and answers with the rules when it cannot.

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
        horizons_minutes: tuple[int, ...] = SHORT_TERM_HORIZONS,
    ) -> None:
        self._service = service
        self._breaker = breaker
        self._enabled = enabled
        self._pseudonymizer = pseudonymizer
        self._store = store
        self._clock = clock
        self._horizons = horizons_minutes
        self._lock = threading.Lock()

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
        if not self._enabled:
            return self._fallback(request, call, FallbackReason.CIRCUIT_OPEN)
        if self._service is None:
            return self._fallback(request, call, FallbackReason.AI_ERROR)
        now = self._clock.now()
        with self._lock:
            allowed = self._breaker.allow(now)
        if not allowed:
            return self._fallback(request, call, FallbackReason.CIRCUIT_OPEN)
        try:
            answer = self._service.glucose_forecast(call)
        except AiCallError as error:
            with self._lock:
                # A 413 or 422 proves the service is alive: the backend sent a bad body.
                if error.counts_as_failure:
                    self._breaker.record_failure(now)
                else:
                    self._breaker.record_success(now)
            return self._fallback(request, call, error.reason)
        with self._lock:
            self._breaker.record_success(now)
        return answer

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
