"""P06 Adapter: the client turns the contract into models and its failures into reasons.

The transport is ``httpx.MockTransport``: no test ever reaches a real network.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from insumap.application.ai.ports import AiCallError, ForecastCall
from insumap.application.common.ids import IdGenerator
from insumap.application.metrics.forecast import FallbackReason, ForecastMode
from insumap.domain.ai.linear_fallback import Trend
from insumap.infrastructure.ai.client_adapter import AiServiceClientAdapter
from insumap.infrastructure.ai.service_token_auth import ServiceTokenAuth

BASE_URL = "https://ai.example.test"
TOKEN = "t" * 43
START = datetime(2026, 11, 14, 21, 30, tzinfo=UTC)
SENTINEL_NAME = "SENTINEL-NOMBRE"
SENTINEL_DOCUMENT = "SENTINEL-DOCUMENTO-123"
SENTINEL_EMAIL = "sentinel@example.test"
PATIENT_ID = UUID("0192f4b2-7c1a-7d00-8a31-5e9f0c2b6a10")
SUBJECT_REF = "sub_5f2c8e7a9b1d4c3e8a6f0d2b7c9e1a43"
type Handler = Callable[[httpx.Request], httpx.Response]


class SequentialIds(IdGenerator):
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


def call(mode: ForecastMode = ForecastMode.SHORT_TERM) -> ForecastCall:
    return ForecastCall(
        subject_ref=SUBJECT_REF,
        mode=mode,
        timestamps=(START, START + timedelta(minutes=5)),
        values_mg_dl=(Decimal("128.0"), Decimal("121.0")),
        interval_minutes=5,
        horizons_minutes=(30, 60, 120),
        quantile_levels=(0.1, 0.5, 0.9),
        low_mg_dl=Decimal("70"),
        high_mg_dl=Decimal("180"),
        clinic_timezone="America/Bogota",
        night_start="00:00",
        night_end="06:00",
    )


def ok_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "request_id": "0192f4b2-7c1a-7d00-8a31-5e9f0c2b6a10",
        "model_name": "chronos-bolt-small",
        "model_version": "2.3.2+chronos-bolt-small",
        "input_hash": "9" * 64,
        "generated_at": "2026-11-14T21:46:02-05:00",
        "is_fallback": False,
        "fallback_reason": None,
        "trend": "FALLING",
        "points": [
            {
                "horizon_minutes": 30,
                "timestamp": "2026-11-14T22:15:00-05:00",
                "p10": 74.0,
                "p50": 92.0,
                "p90": 108.0,
            }
        ],
        "risk": {
            "hypo_probability": [{"horizon_minutes": 30, "probability": 0.06}],
            "hyper_probability": [{"horizon_minutes": 30, "probability": 0.0}],
        },
        "explanation": {
            "summary": "Glucosa en descenso.",
            "factors": [
                {
                    "name": "recent_slope",
                    "direction": "INCREASES_RISK",
                    "value": -1.3,
                    "unit": "mg/dL/min",
                    "contribution": 0.7,
                }
            ],
            "data_refs": [
                {
                    "kind": "READINGS",
                    "from": "2026-11-14T21:30:00-05:00",
                    "to": "2026-11-14T21:45:00-05:00",
                    "count": 4,
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def adapter(handler: Handler, *, token: str = TOKEN) -> AiServiceClientAdapter:
    client = httpx.Client(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        auth=ServiceTokenAuth(SecretStr(token)),
        follow_redirects=False,
    )
    return AiServiceClientAdapter(
        client=client,
        request_ids=SequentialIds(),
        connect_seconds=2.0,
        forecast_seconds=3.0,
        risk_seconds=3.0,
        summary_seconds=30.0,
        assistant_seconds=20.0,
    )


def respond(
    status: int, body: object | None = None, *, raw: str | None = None
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        if raw is not None:
            return httpx.Response(status, content=raw.encode())
        return httpx.Response(status, json=body)

    return handler


def failure_of(handler: Handler) -> AiCallError:
    with pytest.raises(AiCallError) as caught:
        adapter(handler).glucose_forecast(call())
    return caught.value


def test_a_successful_forecast_becomes_the_application_model() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ok_payload())

    result = adapter(handler).glucose_forecast(call())

    assert result.model_version == "2.3.2+chronos-bolt-small"
    assert result.is_fallback is False
    assert result.trend is Trend.FALLING
    (point,) = result.points
    assert point.p10 == Decimal("74.0")
    assert point.p90 == Decimal("108.0")
    (risk,) = result.risk
    assert risk.hypo_probability == Decimal("0.06")
    assert result.explanation is not None
    assert result.explanation.factors == ("recent_slope",)
    request = seen[0]
    assert request.url.path == "/v1/glucose-forecasts"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["X-Request-Id"] == str(UUID(int=1))


def test_the_body_is_a_whitelist_without_identifiers_or_names() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=ok_payload())

    adapter(handler).glucose_forecast(call())

    body = seen[0]
    assert set(body) == {
        "subject_ref",
        "mode",
        "series",
        "horizons_minutes",
        "quantile_levels",
        "thresholds",
        "clinic_timezone",
        "night_window",
    }
    serialized = json.dumps(body)
    for forbidden in (
        str(PATIENT_ID),
        SENTINEL_NAME,
        SENTINEL_DOCUMENT,
        SENTINEL_EMAIL,
        "patient_id",
        "birth",
    ):
        assert forbidden not in serialized
    assert body["subject_ref"] == SUBJECT_REF


def test_overnight_requests_carry_no_horizons() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=ok_payload())

    adapter(handler).glucose_forecast(call(ForecastMode.OVERNIGHT))

    assert "horizons_minutes" not in seen[0]
    assert seen[0]["mode"] == "OVERNIGHT"


@pytest.mark.parametrize(
    ("status", "reason", "counts"),
    [
        (401, FallbackReason.AI_ERROR, True),
        (503, FallbackReason.AI_ERROR, True),
        (500, FallbackReason.AI_ERROR, True),
        (502, FallbackReason.AI_ERROR, True),
        (413, FallbackReason.AI_ERROR, False),
        (422, FallbackReason.AI_ERROR, False),
        (404, FallbackReason.AI_ERROR, False),
    ],
)
def test_http_failures_map_to_their_reason_and_counting(
    status: int, reason: FallbackReason, counts: bool
) -> None:
    error = failure_of(respond(status, {"error": {"code": "X"}}))

    assert error.reason is reason
    assert error.counts_as_failure is counts


def test_a_timeout_is_ai_timeout_and_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    error = failure_of(handler)

    assert error.reason is FallbackReason.AI_TIMEOUT
    assert error.counts_as_failure is True
    assert calls == 1


def test_a_network_error_is_retried_once_then_counts() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    error = failure_of(handler)

    assert error.reason is FallbackReason.AI_ERROR
    assert error.counts_as_failure is True
    assert calls == 2


def test_a_network_error_followed_by_an_answer_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=ok_payload())

    result = adapter(handler).glucose_forecast(call())

    assert calls == 2
    assert result.model_name == "chronos-bolt-small"


@pytest.mark.parametrize(
    "payload",
    [
        ok_payload(
            points=[
                {
                    "horizon_minutes": 30,
                    "timestamp": "2026-11-14T22:15:00-05:00",
                    "p10": 110.0,
                    "p50": 92.0,
                    "p90": 108.0,
                }
            ]
        ),
        ok_payload(is_fallback=True, fallback_reason=None),
        ok_payload(is_fallback=False, fallback_reason="AI_ERROR"),
        ok_payload(input_hash="short"),
    ],
)
def test_an_answer_that_breaks_the_contract_is_ai_error(
    payload: dict[str, object],
) -> None:
    error = failure_of(respond(200, payload))

    assert error.reason is FallbackReason.AI_ERROR
    assert error.counts_as_failure is True


def test_not_finite_numbers_are_refused() -> None:
    raw = json.dumps(ok_payload()).replace("74.0", "NaN")

    error = failure_of(respond(200, raw=raw))

    assert error.counts_as_failure is True


def test_unknown_response_fields_are_ignored() -> None:
    result = adapter(respond(200, ok_payload(extra_field="ignored"))).glucose_forecast(
        call()
    )

    assert result.model_version == "2.3.2+chronos-bolt-small"


def test_a_service_fallback_is_returned_as_is() -> None:
    payload = ok_payload(
        is_fallback=True,
        fallback_reason="INSUFFICIENT_DATA",
        points=[],
        risk={"hypo_probability": [], "hyper_probability": []},
        trend=None,
        model_version="fallback-linear@1.0.0",
    )

    result = adapter(respond(200, payload)).glucose_forecast(call())

    assert result.is_fallback is True
    assert result.fallback_reason is FallbackReason.INSUFFICIENT_DATA
    assert result.points == ()


def test_a_redirect_is_not_followed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example.test"})

    error = failure_of(handler)

    assert error.counts_as_failure is False
    assert seen == [f"{BASE_URL}/v1/glucose-forecasts"]


def test_the_token_is_not_in_its_repr() -> None:
    assert TOKEN not in repr(ServiceTokenAuth(SecretStr(TOKEN)))
