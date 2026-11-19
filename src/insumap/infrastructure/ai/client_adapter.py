"""HTTP client of ``insumap-ai`` (Contrato-IA): the only class that knows its JSON.

Pattern: P06 Adapter. It turns the wire format into the application's models and
the HTTP failures into ``AiCallError`` with the reason the contract defines. It
never logs a body, never follows a redirect, and retries only network errors
(Contrato-IA 3.2): a timeout is never retried.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, final, override

import httpx
from pydantic import BaseModel, ValidationError

from insumap.application.ai.assessments import (
    AiExplanation,
    EscalationLevel,
    SummarySection,
)
from insumap.application.ai.ports import (
    AiCallError,
    AiServicePort,
    AssistantCall,
    ForecastCall,
    RemoteAssistant,
    RemoteForecast,
    RemoteRisk,
    RemoteSummary,
    RiskCall,
    SummaryCall,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.metrics.forecast import (
    FallbackReason,
    ForecastExplanation,
    ForecastPoint,
    ForecastRisk,
)
from insumap.domain.ai.risk import RiskTier
from insumap.infrastructure.ai.contract_models import (
    AssistantReplyResponse,
    ClinicalSummaryResponse,
    ExplanationModel,
    GlucoseForecastResponse,
    RiskAssessmentResponse,
)
from insumap.infrastructure.ai.wire import (
    assistant_body,
    forecast_body,
    risk_body,
    summary_body,
)

FORECAST_PATH: Final = "/v1/glucose-forecasts"
RISK_PATH: Final = "/v1/risk-assessments"
SUMMARY_PATH: Final = "/v1/clinical-summaries"
ASSISTANT_PATH: Final = "/v1/assistant-replies"
REQUEST_ID_HEADER: Final = "X-Request-Id"
NETWORK_RETRIES: Final = 1
"""Retried once, and only after a network error, for forecasts and risk."""
NO_RETRIES: Final = 0
"""The LLM calls (IA5, IA6) are never retried (Contrato-IA 3.2)."""
HTTP_OK: Final = 200
HTTP_UNAUTHORIZED: Final = 401
HTTP_SERVER_ERROR: Final = 500
HTTP_SERVICE_UNAVAILABLE: Final = 503


@final
class AiServiceClientAdapter(AiServicePort):
    """Calls the service with the timeouts of the settings, one set per endpoint.

    Pattern: P06 Adapter
    """

    def __init__(
        self,
        *,
        client: httpx.Client,
        request_ids: IdGenerator,
        connect_seconds: float,
        forecast_seconds: float,
        risk_seconds: float,
        summary_seconds: float,
        assistant_seconds: float,
    ) -> None:
        self._client = client
        self._request_ids = request_ids
        self._connect = connect_seconds
        self._forecast = forecast_seconds
        self._risk = risk_seconds
        self._summary = summary_seconds
        self._assistant = assistant_seconds

    @override
    def glucose_forecast(self, call: ForecastCall) -> RemoteForecast:
        payload = self._post(
            FORECAST_PATH,
            forecast_body(call),
            GlucoseForecastResponse,
            seconds=self._forecast,
            retries=NETWORK_RETRIES,
        )
        return _to_remote(payload)

    @override
    def risk_assessment(self, call: RiskCall) -> RemoteRisk:
        payload = self._post(
            RISK_PATH,
            risk_body(call),
            RiskAssessmentResponse,
            seconds=self._risk,
            retries=NETWORK_RETRIES,
        )
        return RemoteRisk(
            model_name=payload.model_name,
            model_version=payload.model_version,
            input_hash=payload.input_hash,
            generated_at=payload.generated_at,
            is_fallback=payload.is_fallback,
            fallback_reason=payload.fallback_reason,
            risk_probability=None
            if payload.risk_probability is None
            else Decimal(str(payload.risk_probability)),
            risk_tier=None
            if payload.risk_tier is None
            else RiskTier(payload.risk_tier),
            calibrated=payload.calibrated,
            explanation=_explanation(payload.explanation),
        )

    @override
    def clinical_summary(self, call: SummaryCall) -> RemoteSummary:
        payload = self._post(
            SUMMARY_PATH,
            summary_body(call),
            ClinicalSummaryResponse,
            seconds=self._summary,
            retries=NO_RETRIES,
        )
        return RemoteSummary(
            model_name=payload.model_name,
            model_version=payload.model_version,
            input_hash=payload.input_hash,
            generated_at=payload.generated_at,
            is_fallback=payload.is_fallback,
            fallback_reason=payload.fallback_reason,
            summary_text=payload.summary_text,
            sections=tuple(
                SummarySection(title=s.title, text=s.text, refs=tuple(s.refs))
                for s in payload.sections
            ),
            numeric_all_matched=payload.numeric_check.all_matched,
            explanation=_explanation(payload.explanation),
        )

    @override
    def assistant_reply(self, call: AssistantCall) -> RemoteAssistant:
        payload = self._post(
            ASSISTANT_PATH,
            assistant_body(call),
            AssistantReplyResponse,
            seconds=self._assistant,
            retries=NO_RETRIES,
        )
        return RemoteAssistant(
            model_name=payload.model_name,
            model_version=payload.model_version,
            input_hash=payload.input_hash,
            generated_at=payload.generated_at,
            is_fallback=payload.is_fallback,
            fallback_reason=payload.fallback_reason,
            reply_text=payload.reply_text,
            citations=tuple(payload.citations),
            escalation=EscalationLevel(payload.escalation.level),
            escalation_message=payload.escalation.message,
            guardrails_triggered=tuple(payload.guardrails_triggered),
            explanation=_explanation(payload.explanation),
        )

    def _post[M: BaseModel](
        self,
        path: str,
        body: Mapping[str, object],
        model: type[M],
        *,
        seconds: float,
        retries: int,
    ) -> M:
        response = self._send(path, dict(body), seconds=seconds, retries=retries)
        return _parse(response, model)

    def _send(
        self, path: str, body: dict[str, object], *, seconds: float, retries: int
    ) -> httpx.Response:
        timeout = httpx.Timeout(seconds, connect=self._connect)
        last_error: httpx.TransportError | None = None
        for _ in range(retries + 1):
            try:
                return self._client.post(
                    path,
                    json=body,
                    headers={REQUEST_ID_HEADER: str(self._request_ids.new_id())},
                    timeout=timeout,
                )
            except httpx.TimeoutException as error:
                raise AiCallError(
                    FallbackReason.AI_TIMEOUT, counts_as_failure=True
                ) from error
            except httpx.TransportError as error:
                last_error = error
        raise AiCallError(
            FallbackReason.AI_ERROR, counts_as_failure=True
        ) from last_error


def _parse[M: BaseModel](response: httpx.Response, model: type[M]) -> M:
    status = response.status_code
    if status == HTTP_OK:
        try:
            return model.model_validate(response.json())
        except (ValidationError, ValueError) as error:
            raise AiCallError(
                FallbackReason.AI_ERROR, counts_as_failure=True
            ) from error
    if status in {HTTP_UNAUTHORIZED, HTTP_SERVICE_UNAVAILABLE}:
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)
    if status >= HTTP_SERVER_ERROR:
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)
    # 413 and 422 mean the backend sent something the contract refuses.
    raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=False)


def _to_remote(payload: GlucoseForecastResponse) -> RemoteForecast:
    hypo = {
        item.horizon_minutes: item.probability for item in payload.risk.hypo_probability
    }
    hyper = {
        item.horizon_minutes: item.probability
        for item in payload.risk.hyper_probability
    }
    if hypo.keys() != hyper.keys():
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)
    return RemoteForecast(
        model_name=payload.model_name,
        model_version=payload.model_version,
        input_hash=payload.input_hash,
        generated_at=payload.generated_at,
        is_fallback=payload.is_fallback,
        fallback_reason=payload.fallback_reason,
        trend=payload.trend,
        points=tuple(
            ForecastPoint(
                horizon_minutes=point.horizon_minutes,
                timestamp=point.timestamp,
                p10=Decimal(str(point.p10)),
                p50=Decimal(str(point.p50)),
                p90=Decimal(str(point.p90)),
            )
            for point in payload.points
        ),
        risk=tuple(
            ForecastRisk(
                horizon_minutes=horizon,
                hypo_probability=Decimal(str(hypo[horizon])),
                hyper_probability=Decimal(str(hyper[horizon])),
            )
            for horizon in sorted(hypo)
        ),
        explanation=_forecast_explanation(payload.explanation),
    )


def _forecast_explanation(model: ExplanationModel) -> ForecastExplanation:
    return ForecastExplanation(
        summary=model.summary,
        factors=tuple(factor.name for factor in model.factors),
        data_refs=tuple(
            _data_ref(ref.kind, ref.from_, ref.to, ref.count) for ref in model.data_refs
        ),
    )


def _explanation(model: ExplanationModel) -> AiExplanation:
    """The explanation the doctor reads, as plain maps (Modulo-IA 5)."""
    factors: list[Mapping[str, Any]] = [
        {
            "name": factor.name,
            "direction": factor.direction,
            "value": factor.value,
            "unit": factor.unit,
            "contribution": float(factor.contribution),
        }
        for factor in model.factors
    ]
    refs: list[Mapping[str, Any]] = [
        {
            "kind": ref.kind,
            "from": ref.from_.isoformat(),
            "to": ref.to.isoformat(),
            "count": ref.count,
        }
        for ref in model.data_refs
    ]
    return AiExplanation(
        summary=model.summary, factors=tuple(factors), data_refs=tuple(refs)
    )


def _data_ref(kind: str, start: datetime, end: datetime, count: int) -> str:
    return f"{kind} {start.isoformat()} {end.isoformat()} {count}"
