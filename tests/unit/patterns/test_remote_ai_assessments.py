"""P11 Proxy for IA2, IA5 and IA6: the service, the breaker, the fallbacks and storage.

No test reaches a network: the service is ``ScriptedAiService`` and the store is
``RecordingAiStore``. The rules, the template and the predefined text are the real ones.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from insumap.application.ai.assessments import (
    AiExplanation,
    ApprovedFragment,
    AssistantRequest,
    AssistantTurn,
    EscalationLevel,
    RiskRequest,
    SummaryRequest,
)
from insumap.application.ai.ports import (
    AiCallError,
    AssistantCall,
    RemoteAssistant,
    RemoteRisk,
    RemoteSummary,
    RiskCall,
    SummaryCall,
)
from insumap.application.metrics.forecast import FallbackReason
from insumap.domain.ai.circuit_breaker import CircuitBreaker, CircuitPolicy
from insumap.domain.ai.risk import (
    AssessmentType,
    FactorDirection,
    RiskFeatures,
    RiskLimits,
    RiskTier,
    RuleBasedRiskStrategy,
)
from insumap.domain.metrics.glycemic_metrics import Confidence, GlycemicMetrics, Signal
from insumap.infrastructure.ai.proxy import (
    RULES_MODEL_NAME,
    TEMPLATE_MODEL_NAME,
    RemoteAiServiceProxy,
)
from insumap.infrastructure.ai.pseudonymizer import HmacPseudonymizer
from insumap.infrastructure.security.subkey_hasher import Subkey, SubkeyHasher
from insumap.shared.i18n.message_catalog import MessageCatalog
from tests.support.ai_assessment_fakes import RecordingAiStore, ScriptedAiService
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds

NOW = datetime(2026, 11, 14, 21, 45, tzinfo=UTC)
PATIENT = UUID("0192f4b2-7c1a-7d00-8a31-5e9f0c2b6a10")
CLINIC = UUID(int=9)
PROFILE = UUID(int=8)
DOCTOR = UUID(int=7)
KEY = bytes(range(32))
CONSENT = UUID(int=55)
SUBJECT = "sub_"
LIMITS = RiskLimits(
    tir_min_pct=Decimal("70"),
    tbr_l1_max_pct=Decimal("4"),
    tbr_l2_max_pct=Decimal("1"),
    tar_l1_max_pct=Decimal("25"),
    tar_l2_max_pct=Decimal("5"),
    cv_max_pct=Decimal("36"),
    min_data_sufficiency_pct=Decimal("70"),
)
MISSED = RiskFeatures(
    data_sufficiency_pct=Decimal("92"),
    tir_pct=Decimal("48.2"),
    tbr_l1_pct=Decimal("6"),
    tbr_l2_pct=Decimal("0.2"),
    tar_l1_pct=Decimal("15"),
    tar_l2_pct=Decimal("2"),
    cv_pct=Decimal("30"),
)


class Harness:
    def __init__(self, *, configured: bool = True, enabled: bool = True) -> None:
        self.service = ScriptedAiService()
        self.store = RecordingAiStore()
        self.clock = FixedClock(NOW)
        self.proxy = RemoteAiServiceProxy(
            service=self.service if configured else None,
            breaker=CircuitBreaker(
                CircuitPolicy(failure_threshold=2, open_for=timedelta(seconds=30))
            ),
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


def risk_request(
    *,
    features: RiskFeatures = MISSED,
    sufficient: bool = True,
    diabetes: str = "T1D",
) -> RiskRequest:
    return RiskRequest(
        patient_id=PATIENT,
        clinic_id=CLINIC,
        target_profile_id=PROFILE,
        window_days=14,
        diabetes_type=diabetes,
        features=features,
        limits=LIMITS,
        is_sufficient=sufficient,
        window_start=NOW - timedelta(days=14),
        window_end=NOW,
    )


def metrics(*, tir: str | None = "48.2", hypo: int | None = 6) -> GlycemicMetrics:
    return GlycemicMetrics(
        signal=Signal.CGM,
        data_sufficiency_pct=Decimal("92"),
        is_sufficient=True,
        confidence=Confidence.NORMAL,
        tir_pct=None if tir is None else Decimal(tir),
        gmi_pct=Decimal("7.5"),
        hypo_events_count=hypo,
    )


def summary_request(
    *, use_llm: bool = True, current: GlycemicMetrics | None = None
) -> SummaryRequest:
    return SummaryRequest(
        patient_id=PATIENT,
        clinic_id=CLINIC,
        target_profile_id=PROFILE,
        requested_by=DOCTOR,
        period_start=NOW - timedelta(days=14),
        period_end=NOW,
        diabetes_type="T1D",
        metrics=current or metrics(),
        target_tir_pct=Decimal("70"),
        is_sufficient=True,
        use_llm=use_llm,
        readings_per_day=Decimal("270"),
    )


def assistant_request(
    *, consent: UUID | None, fragments: tuple[ApprovedFragment, ...] = ()
) -> AssistantRequest:
    return AssistantRequest(
        clinic_id=CLINIC,
        patient_id=PATIENT,
        conversation_id=UUID(int=300),
        message="¿Qué hago si tiemblo?",
        history=(AssistantTurn(sender="PATIENT", text="Hola"),),
        fragments=fragments,
        external_consent_id=consent,
    )


DOC = ApprovedFragment(doc_id=UUID(int=501), title="Hipoglucemia", text="Temblor.")


def test_risk_without_enough_data_is_insufficient_and_never_calls_the_service() -> None:
    harness = Harness()

    result = harness.proxy.assess(risk_request(sufficient=False))

    assert harness.service.calls == []
    assert result.fallback_reason is FallbackReason.INSUFFICIENT_DATA
    assert result.risk_probability is None
    (record,) = harness.store.risks
    assert record.output is result
    assert record.window_days == 14


def test_risk_without_the_service_answers_with_the_rules_and_says_so() -> None:
    harness = Harness(configured=False)

    result = harness.proxy.assess(risk_request())

    assert result.is_fallback is True
    assert result.fallback_reason is FallbackReason.AI_ERROR
    assert result.model_name == RULES_MODEL_NAME
    assert result.calibrated is False
    assert result.risk_tier is RiskTier.HIGH
    assert result.risk_probability == Decimal("0.3333")
    assert "2 de 6 indicadores fuera de meta" in result.explanation.summary
    assert (
        result.explanation.factors[0]["direction"]
        == FactorDirection.INCREASES_RISK.value
    )
    assert len(harness.store.risks) == 1


def test_risk_answered_by_the_service_is_stored_as_it_came() -> None:
    harness = Harness()
    harness.service.risk = RemoteRisk(
        model_name="risk-gbm",
        model_version="0.3.0+sim1.0.0.seed42",
        input_hash="a" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        risk_probability=Decimal("0.64"),
        risk_tier=RiskTier.HIGH,
        calibrated=True,
        explanation=_empty_explanation(),
    )

    result = harness.proxy.assess(risk_request())

    assert result.is_fallback is False
    assert result.calibrated is True
    assert result.risk_probability == Decimal("0.64")
    (call,) = harness.service.calls
    assert isinstance(call, RiskCall)
    assert call.diabetes_type == "T1D"
    assert call.target_tir_pct == Decimal("70")


def test_the_risk_call_carries_the_pseudonym_and_never_the_patient_id() -> None:
    harness = Harness()
    harness.service.risk = RemoteRisk(
        model_name="risk-gbm",
        model_version="0.3.0",
        input_hash="a" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        risk_probability=Decimal("0.1"),
        risk_tier=RiskTier.LOW,
        calibrated=True,
        explanation=_empty_explanation(),
    )

    harness.proxy.assess(risk_request())

    (call,) = harness.service.calls
    assert isinstance(call, RiskCall)
    assert call.subject_ref.startswith(SUBJECT)
    assert str(PATIENT) not in call.subject_ref
    assert str(PATIENT) not in repr(call)


def test_a_diabetes_type_the_contract_does_not_know_falls_back_without_a_call() -> None:
    harness = Harness()

    result = harness.proxy.assess(risk_request(diabetes="OTHER"))

    assert harness.service.calls == []
    assert result.fallback_reason is FallbackReason.AI_ERROR


def test_a_timeout_of_the_service_becomes_its_reason_on_the_fallback() -> None:
    harness = Harness()
    harness.service.fail = FallbackReason.AI_TIMEOUT

    result = harness.proxy.assess(risk_request())

    assert result.fallback_reason is FallbackReason.AI_TIMEOUT
    assert result.model_name == RULES_MODEL_NAME


def test_the_breaker_opens_after_repeated_failures_and_answers_circuit_open() -> None:
    harness = Harness()
    harness.service.fail = FallbackReason.AI_ERROR

    harness.proxy.assess(risk_request())
    harness.proxy.assess(risk_request())
    result = harness.proxy.assess(risk_request())

    assert len(harness.service.calls) == 2
    assert result.fallback_reason is FallbackReason.CIRCUIT_OPEN


def test_a_summary_without_llm_permission_is_the_template_and_no_call() -> None:
    harness = Harness()

    result = harness.proxy.summarize(summary_request(use_llm=False))

    assert harness.service.calls == []
    assert result.model_name == TEMPLATE_MODEL_NAME
    assert result.fallback_reason is FallbackReason.CIRCUIT_OPEN
    assert isinstance(result.summary_id, UUID)
    assert harness.store.summaries[0].output.summary_id == result.summary_id
    assert [section.title for section in result.sections] == [
        "Resumen del periodo",
        "Registro",
    ]
    assert "TIR 48,20 %" in result.sections[0].text
    (record,) = harness.store.summaries
    assert record.output is result


def test_a_summary_from_the_service_is_stored_when_its_numbers_match() -> None:
    harness = Harness()
    harness.service.summary = RemoteSummary(
        model_name="clinical-summary-llm",
        model_version="0.1.0",
        input_hash="b" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        summary_text="Resumen.",
        sections=(),
        numeric_all_matched=True,
        explanation=_empty_explanation(),
    )

    result = harness.proxy.summarize(summary_request())

    assert result.is_fallback is False
    assert result.summary_text == "Resumen."
    assert isinstance(harness.service.calls[0], SummaryCall)


def test_a_summary_whose_numbers_do_not_match_is_replaced_by_the_template() -> None:
    harness = Harness()
    harness.service.summary = RemoteSummary(
        model_name="clinical-summary-llm",
        model_version="0.1.0",
        input_hash="b" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        summary_text="Cifras inventadas.",
        sections=(),
        numeric_all_matched=False,
        explanation=_empty_explanation(),
    )

    result = harness.proxy.summarize(summary_request())

    assert result.model_name == TEMPLATE_MODEL_NAME
    assert result.fallback_reason is FallbackReason.AI_ERROR
    assert "Cifras inventadas." not in result.summary_text


def test_a_summary_without_the_key_figures_says_insufficient_data() -> None:
    harness = Harness()

    result = harness.proxy.summarize(summary_request(current=metrics(tir=None)))

    assert result.fallback_reason is FallbackReason.INSUFFICIENT_DATA
    assert result.sections == ()
    assert result.summary_text == "Datos insuficientes para resumir el periodo."


def test_the_assistant_without_consent_predefines_the_reply_and_never_calls() -> None:
    harness = Harness()

    result = harness.proxy.reply(assistant_request(consent=None, fragments=(DOC,)))

    assert harness.service.calls == []
    assert result.is_fallback is True
    assert result.fallback_reason is FallbackReason.CIRCUIT_OPEN
    assert result.escalation is EscalationLevel.NONE
    assert "llama a emergencias" in result.reply_text
    (record,) = harness.store.replies
    assert record.external_consent_id is None
    assert record.output is result


def test_the_assistant_reply_keeps_only_citations_of_the_sent_material() -> None:
    harness = Harness()
    harness.service.reply = RemoteAssistant(
        model_name="assistant-llm",
        model_version="0.1.0",
        input_hash="c" * 64,
        generated_at=NOW,
        is_fallback=False,
        fallback_reason=None,
        reply_text="Mide tu glucosa.",
        citations=(str(DOC.doc_id), "doc-inventado"),
        escalation=EscalationLevel.EMERGENCY,
        escalation_message="Llama a emergencias.",
        guardrails_triggered=("EMERGENCY_SYMPTOM",),
        explanation=_empty_explanation(),
    )

    result = harness.proxy.reply(assistant_request(consent=CONSENT, fragments=(DOC,)))

    assert result.citations == (DOC.doc_id,)
    assert result.escalation is EscalationLevel.EMERGENCY
    assert result.guardrails_triggered == ("EMERGENCY_SYMPTOM",)
    assert isinstance(harness.service.calls[0], AssistantCall)
    (record,) = harness.store.replies
    assert record.context_doc_ids == (DOC.doc_id,)
    assert record.external_consent_id == CONSENT


def test_the_assistant_falls_back_to_the_predefined_text_when_the_service_fails() -> (
    None
):
    harness = Harness()
    harness.service.fail = FallbackReason.AI_TIMEOUT

    result = harness.proxy.reply(assistant_request(consent=CONSENT, fragments=(DOC,)))

    assert result.fallback_reason is FallbackReason.AI_TIMEOUT
    assert result.citations == ()
    assert "llama a emergencias" in result.reply_text


def test_an_unconfigured_service_is_the_same_fallback_as_a_failure() -> None:
    harness = Harness(configured=False)

    result = harness.proxy.reply(assistant_request(consent=CONSENT))

    assert result.fallback_reason is FallbackReason.AI_ERROR


def test_a_bad_request_answer_falls_back_without_opening_the_breaker() -> None:
    harness = Harness()
    attempts: list[int] = []

    def refuse(call: object) -> None:  # the service refuses the body: a backend fault
        del call
        attempts.append(1)
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=False)

    harness.service.assistant_reply = refuse  # type: ignore[method-assign,assignment]

    for _ in range(3):
        result = harness.proxy.reply(assistant_request(consent=CONSENT))

    assert len(attempts) == 3
    assert result.fallback_reason is FallbackReason.AI_ERROR


def test_the_rules_use_the_same_assessment_type_as_the_store_expects() -> None:
    assert AssessmentType.DETERIORATION.value == "DETERIORATION"


def _empty_explanation() -> AiExplanation:
    return AiExplanation(summary="ok")
