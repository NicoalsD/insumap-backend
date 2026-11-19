"""P06 Adapter for IA2, IA5 and IA6: the contract in, the models out, the failures as
reasons.

The transport is ``httpx.MockTransport``: no test reaches a real network. The
retry policy follows Contrato-IA 3.2: risk is retried once after a network error,
the LLM calls (IA5, IA6) are never retried, and a timeout is never retried.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from insumap.application.ai.assessments import (
    ApprovedFragment,
    AssistantTurn,
    EscalationLevel,
)
from insumap.application.ai.ports import (
    AiCallError,
    AssistantCall,
    RiskCall,
    SummaryCall,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.metrics.forecast import FallbackReason
from insumap.domain.ai.risk import RiskFeatures, RiskTier
from insumap.domain.metrics.glycemic_metrics import Confidence, GlycemicMetrics, Signal
from insumap.infrastructure.ai.client_adapter import AiServiceClientAdapter
from insumap.infrastructure.ai.service_token_auth import ServiceTokenAuth

BASE_URL = "https://ai.example.test"
TOKEN = "t" * 43
SUBJECT_REF = "sub_5f2c8e7a9b1d4c3e8a6f0d2b7c9e1a43"
DOC_ID = UUID(int=77)
NOW_ISO = "2026-11-15T06:00:04-05:00"
EXPLANATION: dict[str, Any] = {
    "summary": "Riesgo alto por tres metas incumplidas.",
    "factors": [
        {
            "name": "tir_pct",
            "direction": "INCREASES_RISK",
            "value": 48.2,
            "unit": "%",
            "contribution": 0.5,
        }
    ],
    "data_refs": [{"kind": "WINDOW", "from": NOW_ISO, "to": NOW_ISO, "count": 3780}],
}
type Handler = Callable[[httpx.Request], httpx.Response]


class SequentialIds(IdGenerator):
    def __init__(self) -> None:
        self._next = 0

    def new_id(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


def adapter(handler: Handler) -> AiServiceClientAdapter:
    client = httpx.Client(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
        auth=ServiceTokenAuth(SecretStr(TOKEN)),
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


def respond(body: dict[str, Any], status: int = 200) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status, json=body)

    return handler


def risk_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_name": "risk-gbm",
        "model_version": "0.3.0+sim1.0.0.seed42",
        "input_hash": "a" * 64,
        "generated_at": NOW_ISO,
        "is_fallback": False,
        "fallback_reason": None,
        "assessment_type": "DETERIORATION",
        "risk_probability": 0.64,
        "calibrated": True,
        "risk_tier": "HIGH",
        "explanation": EXPLANATION,
    }
    payload.update(overrides)
    return payload


def summary_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_name": "clinical-summary-llm",
        "model_version": "0.1.0+prompt-v3",
        "input_hash": "b" * 64,
        "generated_at": NOW_ISO,
        "is_fallback": False,
        "fallback_reason": None,
        "summary_text": "El TIR fue 48,2 %.",
        "sections": [
            {"title": "Periodo", "text": "TIR 48,2 %.", "refs": ["metric:tir_pct"]}
        ],
        "numeric_check": {
            "numbers_in_text": 1,
            "numbers_matched": 1,
            "all_matched": True,
        },
        "explanation": EXPLANATION,
    }
    payload.update(overrides)
    return payload


def assistant_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_name": "assistant-llm",
        "model_version": "0.1.0+prompt-v2",
        "input_hash": "c" * 64,
        "generated_at": NOW_ISO,
        "is_fallback": False,
        "fallback_reason": None,
        "reply_text": "Mide tu glucosa y avisa a tu equipo.",
        "citations": [str(DOC_ID)],
        "escalation": {"level": "CONTACT_DOCTOR", "message": "Avisaremos a tu equipo."},
        "guardrails_triggered": [],
        "explanation": {
            "summary": "Material aprobado.",
            "factors": [],
            "data_refs": [],
        },
    }
    payload.update(overrides)
    return payload


def features() -> RiskFeatures:
    return RiskFeatures(data_sufficiency_pct=Decimal("92"), tir_pct=Decimal("48.2"))


def risk_call() -> RiskCall:
    return RiskCall(
        subject_ref=SUBJECT_REF,
        window_days=14,
        diabetes_type="T1D",
        target_tir_pct=Decimal("70"),
        features=features(),
    )


def summary_call() -> SummaryCall:
    metrics = GlycemicMetrics(
        signal=Signal.CGM,
        data_sufficiency_pct=Decimal("92"),
        is_sufficient=True,
        confidence=Confidence.NORMAL,
        tir_pct=Decimal("48.2"),
        gmi_pct=Decimal("7.5"),
    )
    moment = datetime(2026, 11, 1, tzinfo=UTC)
    return SummaryCall(
        subject_ref=SUBJECT_REF,
        period_start=moment,
        period_end=moment,
        diabetes_type="T1D",
        metrics=metrics,
        target_tir_pct=Decimal("70"),
        readings_per_day=Decimal("270"),
    )


def assistant_call() -> AssistantCall:
    return AssistantCall(
        subject_ref=SUBJECT_REF,
        message="¿Qué hago si tiemblo?",
        history=(AssistantTurn(sender="PATIENT", text="Hola"),),
        fragments=(
            ApprovedFragment(doc_id=DOC_ID, title="Hipoglucemia", text="Temblor."),
        ),
    )


def test_risk_posts_the_minimized_body_and_reads_the_answer() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/risk-assessments"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=risk_payload())

    answer = adapter(handler).risk_assessment(risk_call())

    assert answer.risk_probability == Decimal("0.64")
    assert answer.risk_tier is RiskTier.HIGH
    assert answer.calibrated is True
    assert answer.explanation.factors[0]["name"] == "tir_pct"
    (body,) = seen
    assert body["subject_ref"] == SUBJECT_REF
    assert body["diabetes_type"] == "T1D"
    assert set(body) == {
        "subject_ref",
        "assessment_type",
        "window_days",
        "diabetes_type",
        "features",
    }


def test_risk_retries_once_after_a_network_error_only() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json=risk_payload())

    answer = adapter(handler).risk_assessment(risk_call())

    assert len(attempts) == 2
    assert answer.risk_tier is RiskTier.HIGH


def test_a_risk_timeout_is_not_retried_and_counts_as_failure() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        attempts.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AiCallError) as raised:
        adapter(handler).risk_assessment(risk_call())

    assert raised.value.reason is FallbackReason.AI_TIMEOUT
    assert raised.value.counts_as_failure is True
    assert len(attempts) == 1


def test_an_unknown_risk_tier_is_a_bad_answer_that_counts_as_failure() -> None:
    with pytest.raises(AiCallError) as raised:
        adapter(respond(risk_payload(risk_tier="EXTREME"))).risk_assessment(risk_call())

    assert raised.value.reason is FallbackReason.AI_ERROR
    assert raised.value.counts_as_failure is True


def test_a_summary_is_never_retried_and_keeps_its_sections() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/clinical-summaries"
        attempts.append(1)
        raise httpx.ConnectError("refused")

    with pytest.raises(AiCallError) as raised:
        adapter(handler).clinical_summary(summary_call())

    assert raised.value.reason is FallbackReason.AI_ERROR
    assert len(attempts) == 1


def test_a_summary_answer_is_parsed_with_its_numeric_check() -> None:
    answer = adapter(
        respond(summary_payload(numeric_check={"all_matched": False}))
    ).clinical_summary(summary_call())

    assert answer.numeric_all_matched is False
    assert answer.sections[0].refs == ("metric:tir_pct",)


def test_an_assistant_reply_is_parsed_with_its_escalation() -> None:
    answer = adapter(respond(assistant_payload())).assistant_reply(assistant_call())

    assert answer.escalation is EscalationLevel.CONTACT_DOCTOR
    assert answer.citations == (str(DOC_ID),)
    assert answer.escalation_message == "Avisaremos a tu equipo."


def test_a_reply_longer_than_the_stored_column_is_refused() -> None:
    with pytest.raises(AiCallError) as raised:
        adapter(respond(assistant_payload(reply_text="x" * 1001))).assistant_reply(
            assistant_call()
        )

    assert raised.value.reason is FallbackReason.AI_ERROR
    assert raised.value.counts_as_failure is True


def test_an_assistant_401_counts_as_failure() -> None:
    with pytest.raises(AiCallError) as raised:
        adapter(respond({"error": {}}, status=401)).assistant_reply(assistant_call())

    assert raised.value.counts_as_failure is True


def test_an_assistant_422_is_the_backend_fault_and_does_not_count() -> None:
    with pytest.raises(AiCallError) as raised:
        adapter(respond({"error": {}}, status=422)).assistant_reply(assistant_call())

    assert raised.value.reason is FallbackReason.AI_ERROR
    assert raised.value.counts_as_failure is False
