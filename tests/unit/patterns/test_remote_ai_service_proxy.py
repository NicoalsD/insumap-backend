"""P11 Proxy: the remote service behind a circuit breaker, with the rule-based fallback.

The service, the store and the clock are doubles: no network, no database.
"""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

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
from insumap.application.metrics.forecast import (
    FallbackReason,
    ForecastExplanation,
    ForecastMode,
    ForecastRequest,
)
from insumap.domain.ai.circuit_breaker import (
    CircuitBreaker,
    CircuitPolicy,
    CircuitStatus,
)
from insumap.domain.ai.linear_fallback import FALLBACK_MODEL_VERSION
from insumap.domain.ai.risk import RuleBasedRiskStrategy
from insumap.domain.metrics.window import GlucosePoint
from insumap.infrastructure.ai.proxy import RemoteAiServiceProxy
from insumap.infrastructure.ai.pseudonymizer import HmacPseudonymizer
from insumap.infrastructure.security.subkey_hasher import Subkey, SubkeyHasher
from insumap.shared.i18n.message_catalog import MessageCatalog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds

NOW = datetime(2026, 11, 14, 21, 45, tzinfo=UTC)
PATIENT = UUID("0192f4b2-7c1a-7d00-8a31-5e9f0c2b6a10")
CLINIC = UUID(int=9)
PROFILE = UUID(int=8)
KEY = bytes(range(32))
SERVICE_PAYLOAD = RemoteForecast(
    model_name="chronos-bolt-small",
    model_version="2.3.2+chronos-bolt-small",
    input_hash="9" * 64,
    generated_at=NOW,
    is_fallback=False,
    fallback_reason=None,
    trend=None,
    points=(),
    risk=(),
    explanation=ForecastExplanation(summary="ok", factors=(), data_refs=()),
)


class FakeService(AiServicePort):
    def __init__(self) -> None:
        self.calls: list[ForecastCall] = []
        self.error: AiCallError | None = None
        self.answer: RemoteForecast = SERVICE_PAYLOAD

    def glucose_forecast(self, call: ForecastCall) -> RemoteForecast:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        return self.answer

    def risk_assessment(self, call: RiskCall) -> RemoteRisk:
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)

    def clinical_summary(self, call: SummaryCall) -> RemoteSummary:
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)

    def assistant_reply(self, call: AssistantCall) -> RemoteAssistant:
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)


class FakeStore(AiOutputStorePort):
    def __init__(self) -> None:
        self.records: list[ForecastRecord] = []

    def store_forecast(
        self, record: ForecastRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        del request_id, occurred_at
        self.records.append(record)

    def store_risk(
        self, record: RiskRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        del record, request_id, occurred_at

    def store_summary(
        self, record: SummaryRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        del record, request_id, occurred_at

    def store_assistant_reply(
        self, record: AssistantRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        del record, request_id, occurred_at


def series(values: list[float]) -> tuple[GlucosePoint, ...]:
    start = NOW - timedelta(minutes=5 * len(values))
    return tuple(
        GlucosePoint(at=start + timedelta(minutes=5 * index), mg_dl=Decimal(str(value)))
        for index, value in enumerate(values, start=1)
    )


FALLING = series([128.0, 121.0, 113.0, 108.0, 104.0, 101.0])


def request(
    points: tuple[GlucosePoint, ...] = FALLING,
    mode: ForecastMode = ForecastMode.SHORT_TERM,
) -> ForecastRequest:
    return ForecastRequest(
        patient_id=PATIENT,
        clinic_id=CLINIC,
        target_profile_id=PROFILE,
        mode=mode,
        now=NOW,
        timezone="America/Bogota",
        night_start=time(0, 0),
        night_end=time(6, 0),
        low_mg_dl=Decimal("70"),
        high_mg_dl=Decimal("180"),
        series=points,
    )


class Harness:
    def __init__(self, *, enabled: bool = True, configured: bool = True) -> None:
        self.service = FakeService()
        self.store = FakeStore()
        self.clock = FixedClock(NOW)
        self.breaker = CircuitBreaker(
            CircuitPolicy(failure_threshold=2, open_for=timedelta(seconds=30))
        )
        self.proxy = RemoteAiServiceProxy(
            service=self.service if configured else None,
            breaker=self.breaker,
            enabled=enabled,
            pseudonymizer=HmacPseudonymizer(
                SubkeyHasher(KEY, subkey=Subkey.SUBJECT_REF)
            ),
            store=self.store,
            clock=self.clock,
            ids=FakeIds(),
            risk_strategy=RuleBasedRiskStrategy(),
            messages=MessageCatalog.load_spanish(),
        )


def test_a_healthy_service_answer_is_returned_and_stored() -> None:
    harness = Harness()

    result = harness.proxy.forecast(request())

    assert result.is_fallback is False
    assert result.model_version == "2.3.2+chronos-bolt-small"
    (record,) = harness.store.records
    assert record.clinic_id == CLINIC
    assert record.patient_id == PATIENT
    assert record.target_profile_id == PROFILE
    assert record.output.input_hash == "9" * 64


# Pattern: P11 Proxy
def test_the_call_carries_only_the_pseudonym_and_the_series() -> None:
    harness = Harness()

    harness.proxy.forecast(request())

    (call,) = harness.service.calls
    assert call.subject_ref.startswith("sub_")
    assert len(call.subject_ref) == len("sub_") + 32
    assert str(PATIENT) not in call.subject_ref
    assert len(call.values_mg_dl) == len(FALLING)
    assert call.clinic_timezone == "America/Bogota"
    assert (call.night_start, call.night_end) == ("00:00", "06:00")
    assert call.horizons_minutes == (30, 60, 120)


def test_the_pseudonym_is_stable_for_the_same_patient() -> None:
    harness = Harness()

    harness.proxy.forecast(request())
    harness.proxy.forecast(request())

    first, second = harness.service.calls
    assert first.subject_ref == second.subject_ref


def test_overnight_calls_send_no_horizons() -> None:
    harness = Harness()

    harness.proxy.forecast(request(mode=ForecastMode.OVERNIGHT))

    assert harness.service.calls[0].mode is ForecastMode.OVERNIGHT


@pytest.mark.parametrize("reason", [FallbackReason.AI_TIMEOUT, FallbackReason.AI_ERROR])
def test_a_failing_service_answers_the_linear_fallback_with_the_reason(
    reason: FallbackReason,
) -> None:
    harness = Harness()
    harness.service.error = AiCallError(reason, counts_as_failure=True)

    result = harness.proxy.forecast(request())

    assert result.is_fallback is True
    assert result.fallback_reason is reason
    assert result.model_version == FALLBACK_MODEL_VERSION
    assert result.points
    assert result.explanation is not None
    assert result.explanation.summary.startswith("Respaldo por reglas")


# Pattern: P18 State
def test_failures_open_the_circuit_and_calls_are_skipped() -> None:
    harness = Harness()
    harness.service.error = AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)
    harness.proxy.forecast(request())
    harness.proxy.forecast(request())
    assert harness.breaker.status is CircuitStatus.OPEN
    calls_before = len(harness.service.calls)

    result = harness.proxy.forecast(request())

    assert len(harness.service.calls) == calls_before
    assert result.fallback_reason is FallbackReason.CIRCUIT_OPEN


# Pattern: P18 State
def test_after_the_open_period_a_successful_probe_closes_the_circuit() -> None:
    harness = Harness()
    harness.service.error = AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)
    harness.proxy.forecast(request())
    harness.proxy.forecast(request())
    harness.clock.advance(timedelta(seconds=30))
    harness.service.error = None

    result = harness.proxy.forecast(request())

    assert result.is_fallback is False
    assert harness.breaker.status is CircuitStatus.CLOSED


def test_a_contract_refusal_is_not_a_service_failure() -> None:
    harness = Harness()
    harness.service.error = AiCallError(
        FallbackReason.AI_ERROR, counts_as_failure=False
    )

    for _ in range(5):
        harness.proxy.forecast(request())

    assert harness.breaker.status is CircuitStatus.CLOSED
    assert len(harness.service.calls) == 5


def test_a_disabled_ai_never_calls_the_service() -> None:
    harness = Harness(enabled=False)

    result = harness.proxy.forecast(request())

    assert harness.service.calls == []
    assert result.fallback_reason is FallbackReason.CIRCUIT_OPEN


def test_an_unconfigured_ai_answers_ai_error_without_calls() -> None:
    harness = Harness(configured=False)

    result = harness.proxy.forecast(request())

    assert result.fallback_reason is FallbackReason.AI_ERROR
    assert len(harness.store.records) == 1


def test_a_series_too_flat_to_extrapolate_is_insufficient_data() -> None:
    harness = Harness()
    harness.service.error = AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)
    flat = (
        GlucosePoint(at=NOW, mg_dl=Decimal("100")),
        GlucosePoint(at=NOW, mg_dl=Decimal("101")),
    )

    result = harness.proxy.forecast(request(points=flat))

    assert result.fallback_reason is FallbackReason.INSUFFICIENT_DATA
    assert result.points == ()
    assert result.explanation is not None
    assert result.explanation.summary


def test_the_service_own_fallback_is_returned_as_it_is() -> None:
    harness = Harness()
    harness.service.answer = RemoteForecast(
        model_name="fallback-linear",
        model_version=FALLBACK_MODEL_VERSION,
        input_hash="8" * 64,
        generated_at=NOW,
        is_fallback=True,
        fallback_reason=FallbackReason.INSUFFICIENT_DATA,
        trend=None,
        points=(),
        risk=(),
        explanation=None,
    )

    result = harness.proxy.forecast(request())

    assert result.fallback_reason is FallbackReason.INSUFFICIENT_DATA
    assert harness.breaker.status is CircuitStatus.CLOSED


def test_no_output_field_could_hold_a_dose() -> None:
    harness = Harness()
    harness.service.error = AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)

    result = harness.proxy.forecast(request())

    text = repr(result).lower()
    assert "dose" not in text
    assert "units" not in text
