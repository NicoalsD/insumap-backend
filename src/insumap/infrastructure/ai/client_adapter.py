"""HTTP client of ``insumap-ai`` (Contrato-IA): the only class that knows its JSON.

Pattern: P06 Adapter. It turns the wire format into the application's models and
the HTTP failures into ``AiCallError`` with the reason the contract defines. It
never logs a body, never follows a redirect and never retries a timeout.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, final, override

import httpx
from pydantic import ValidationError

from insumap.application.ai.ports import (
    AiCallError,
    AiServicePort,
    ForecastCall,
    RemoteForecast,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.metrics.forecast import (
    FallbackReason,
    ForecastExplanation,
    ForecastPoint,
    ForecastRisk,
)
from insumap.infrastructure.ai.contract_models import (
    ExplanationModel,
    GlucoseForecastResponse,
)
from insumap.infrastructure.ai.wire import forecast_body

FORECAST_PATH: Final = "/v1/glucose-forecasts"
REQUEST_ID_HEADER: Final = "X-Request-Id"
FORECAST_RETRIES: Final = 1
"""Retried once, and only after a network error (Contrato-IA 3.2)."""
HTTP_OK: Final = 200
HTTP_UNAUTHORIZED: Final = 401
HTTP_SERVER_ERROR: Final = 500
HTTP_SERVICE_UNAVAILABLE: Final = 503


@final
class AiServiceClientAdapter(AiServicePort):
    """Calls the service with the timeouts of the settings.

    Pattern: P06 Adapter
    """

    def __init__(
        self,
        *,
        client: httpx.Client,
        request_ids: IdGenerator,
        connect_seconds: float,
        forecast_seconds: float,
    ) -> None:
        self._client = client
        self._request_ids = request_ids
        self._timeout = httpx.Timeout(forecast_seconds, connect=connect_seconds)

    @override
    def glucose_forecast(self, call: ForecastCall) -> RemoteForecast:
        response = self._send(FORECAST_PATH, forecast_body(call))
        payload = _parse(response)
        return _to_remote(payload)

    def _send(self, path: str, body: dict[str, object]) -> httpx.Response:
        last_error: httpx.TransportError | None = None
        for _ in range(FORECAST_RETRIES + 1):
            try:
                return self._client.post(
                    path,
                    json=body,
                    headers={REQUEST_ID_HEADER: str(self._request_ids.new_id())},
                    timeout=self._timeout,
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


def _parse(response: httpx.Response) -> GlucoseForecastResponse:
    status = response.status_code
    if status == HTTP_OK:
        try:
            return GlucoseForecastResponse.model_validate(response.json())
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
        explanation=_explanation(payload.explanation),
    )


def _explanation(model: ExplanationModel) -> ForecastExplanation:
    return ForecastExplanation(
        summary=model.summary,
        factors=tuple(factor.name for factor in model.factors),
        data_refs=tuple(
            _data_ref(ref.kind, ref.from_, ref.to, ref.count) for ref in model.data_refs
        ),
    )


def _data_ref(kind: str, start: datetime, end: datetime, count: int) -> str:
    return f"{kind} {start.isoformat()} {end.isoformat()} {count}"
