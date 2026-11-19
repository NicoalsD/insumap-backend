"""The AI slice: the AI ports over one proxy, one breaker, and the reads of the AI
tables.

Built once by ``Container``. Without ``AI_SERVICE_URL`` or ``AI_SERVICE_TOKEN``
the service is absent and every AI call answers with its fallback: the proxy is
always there, so the endpoints never fail because the AI does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import httpx

from insumap.application.ai.assessments import (
    AssistantPort,
    ClinicalSummaryPort,
    RiskAssessmentPort,
)
from insumap.application.ai.recommendations import (
    OpenPlanDraftPort,
    RecommendationRepositoryPort,
)
from insumap.application.ai.records import (
    AiEvaluationReadPort,
    ApprovedKnowledgePort,
    AssistantConversationPort,
    ClinicalSummaryReadPort,
    DropoutRiskClinicReadPort,
    DropoutRiskReadPort,
    PatientAiProfilePort,
    PatternFindingReadPort,
    PatternFindingReviewPort,
    PlatformAiEvaluationReadPort,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import TransactionFactory
from insumap.application.metrics.forecast import GlucoseForecastPort
from insumap.domain.ai.circuit_breaker import CircuitBreaker, CircuitPolicy
from insumap.domain.ai.risk import RuleBasedRiskStrategy
from insumap.infrastructure.ai.client_adapter import AiServiceClientAdapter
from insumap.infrastructure.ai.output_store import SqlAiOutputStore
from insumap.infrastructure.ai.plan_draft import TreatmentPlanDraftOpener
from insumap.infrastructure.ai.proxy import SHORT_TERM_HORIZONS, RemoteAiServiceProxy
from insumap.infrastructure.ai.pseudonymizer import HmacPseudonymizer
from insumap.infrastructure.ai.service_token_auth import ServiceTokenAuth
from insumap.infrastructure.persistence.ai_read_repositories import (
    SqlAiEvaluationReads,
    SqlApprovedKnowledge,
    SqlAssistantConversation,
    SqlClinicalSummaryReads,
    SqlDropoutRiskClinicReads,
    SqlDropoutRiskReads,
    SqlPatientAiProfile,
    SqlPatternFindingReads,
    SqlPlatformAiEvaluationReads,
)
from insumap.infrastructure.persistence.pattern_finding_review_repository import (
    SqlPatternFindingReviews,
)
from insumap.infrastructure.persistence.recommendation_repository import (
    RecommendationRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.persistence.treatment_repositories import (
    TreatmentPlanRepository,
)
from insumap.infrastructure.security.subkey_hasher import Subkey, SubkeyHasher
from insumap.shared.config import Settings
from insumap.shared.i18n.message_catalog import MessageCatalog
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class AiAdapters:
    """Ports of the AI slice, wired by ``Container``."""

    forecasts: GlucoseForecastPort
    recommendations: RecommendationRepositoryPort
    drafts: OpenPlanDraftPort
    risks: RiskAssessmentPort
    summaries: ClinicalSummaryPort
    assistant: AssistantPort
    findings: PatternFindingReadPort
    pattern_reviews: PatternFindingReviewPort
    dropout: DropoutRiskReadPort
    dropout_clinic: DropoutRiskClinicReadPort
    summary_reads: ClinicalSummaryReadPort
    evaluations: AiEvaluationReadPort
    platform_evaluations: PlatformAiEvaluationReadPort
    patient_profiles: PatientAiProfilePort
    conversations: AssistantConversationPort
    knowledge: ApprovedKnowledgePort


def build_ai_adapters(
    *,
    settings: Settings,
    clock: Clock,
    current: CurrentSession,
    transactions: TransactionFactory,
    ids: IdGenerator,
    app_hmac_key: bytes,
    messages: MessageCatalog,
) -> AiAdapters:
    """Production adapters: the HTTP client when configured, the proxy always."""
    service = None
    token = settings.ai_service_token
    if settings.ai_service_url is not None and token is not None:
        client = httpx.Client(
            base_url=settings.ai_service_url,
            auth=ServiceTokenAuth(token),
            follow_redirects=False,
        )
        service = AiServiceClientAdapter(
            client=client,
            request_ids=ids,
            connect_seconds=settings.ai_timeout_connect_seconds,
            forecast_seconds=settings.ai_timeout_forecast_seconds,
            risk_seconds=settings.ai_timeout_risk_seconds,
            summary_seconds=settings.ai_timeout_summary_seconds,
            assistant_seconds=settings.ai_timeout_assistant_seconds,
        )
    breaker = CircuitBreaker(
        CircuitPolicy(
            failure_threshold=settings.ai_circuit_failure_threshold,
            open_for=timedelta(seconds=settings.ai_circuit_open_seconds),
        )
    )
    proxy = RemoteAiServiceProxy(
        service=service,
        breaker=breaker,
        enabled=settings.ai_enabled,
        pseudonymizer=HmacPseudonymizer(
            SubkeyHasher(app_hmac_key, subkey=Subkey.SUBJECT_REF)
        ),
        store=SqlAiOutputStore(current, transactions, ids),
        clock=clock,
        ids=ids,
        risk_strategy=RuleBasedRiskStrategy(),
        messages=messages,
        horizons_minutes=SHORT_TERM_HORIZONS,
    )
    return AiAdapters(
        forecasts=proxy,
        recommendations=RecommendationRepository(current, ids),
        drafts=TreatmentPlanDraftOpener(TreatmentPlanRepository(current), ids),
        risks=proxy,
        summaries=proxy,
        assistant=proxy,
        findings=SqlPatternFindingReads(current),
        pattern_reviews=SqlPatternFindingReviews(current),
        dropout=SqlDropoutRiskReads(current),
        dropout_clinic=SqlDropoutRiskClinicReads(current),
        summary_reads=SqlClinicalSummaryReads(current),
        evaluations=SqlAiEvaluationReads(current),
        platform_evaluations=SqlPlatformAiEvaluationReads(current),
        patient_profiles=SqlPatientAiProfile(current),
        conversations=SqlAssistantConversation(current, ids),
        knowledge=SqlApprovedKnowledge(current),
    )
