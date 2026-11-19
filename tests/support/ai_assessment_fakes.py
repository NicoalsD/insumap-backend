"""In-memory doubles of the AI ports used by the assessment endpoints.

No network and no database.

The proxy is real: ``AiWorld`` wires ``RemoteAiServiceProxy`` over a
``ScriptedAiService`` and a ``RecordingAiStore``, so the fallbacks, the storage
decisions and the minimization are exercised exactly as in production.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, final, override
from uuid import UUID

from insumap.application.ai.assessments import ApprovedFragment, AssistantTurn
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
from insumap.application.ai.recommendations import (
    OpenPlanDraftPort,
    RecommendationRepositoryPort,
)
from insumap.application.ai.records import (
    AiEvaluationFilter,
    AiEvaluationReadPort,
    AiEvaluationView,
    ApprovedKnowledgePort,
    AssistantConversationPort,
    ClinicalSummaryReadPort,
    ClinicalSummaryView,
    DropoutRiskClinicReadPort,
    DropoutRiskReadPort,
    DropoutRiskView,
    PatientAiProfilePort,
    PatternFindingReadPort,
    PatternFindingReviewPort,
    PatternFindingView,
    PlatformAiEvaluationReadPort,
)
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.metrics.forecast import FallbackReason
from insumap.domain.ai.circuit_breaker import CircuitBreaker, CircuitPolicy
from insumap.domain.ai.finding_review import FindingDismissal
from insumap.domain.ai.risk import RiskTier, RuleBasedRiskStrategy
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.infrastructure.ai.proxy import RemoteAiServiceProxy
from insumap.infrastructure.ai.pseudonymizer import HmacPseudonymizer
from insumap.infrastructure.ai_adapters import AiAdapters
from insumap.infrastructure.security.subkey_hasher import Subkey, SubkeyHasher
from insumap.shared.i18n.message_catalog import MessageCatalog
from insumap.shared.key_material import decode_key


@final
class ScriptedAiService(AiServicePort):
    """The service of a test: it answers what the test scripts, or fails the way asked.

    ``fail`` makes every call raise ``AiCallError``; the default answer of each
    capability is ``None``, which means "not scripted": the call raises ``AI_ERROR``.
    """

    def __init__(self) -> None:
        self.calls: list[ForecastCall | RiskCall | SummaryCall | AssistantCall] = []
        self.fail: FallbackReason | None = None
        self.risk: RemoteRisk | None = None
        self.summary: RemoteSummary | None = None
        self.reply: RemoteAssistant | None = None

    def _answer[T](
        self,
        call: ForecastCall | RiskCall | SummaryCall | AssistantCall,
        scripted: T | None,
    ) -> T:
        self.calls.append(call)
        if self.fail is not None:
            raise AiCallError(self.fail, counts_as_failure=True)
        if scripted is None:
            raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)
        return scripted

    @override
    def glucose_forecast(self, call: ForecastCall) -> RemoteForecast:
        raise AiCallError(FallbackReason.AI_ERROR, counts_as_failure=True)

    @override
    def risk_assessment(self, call: RiskCall) -> RemoteRisk:
        return self._answer(call, self.risk)

    @override
    def clinical_summary(self, call: SummaryCall) -> RemoteSummary:
        return self._answer(call, self.summary)

    @override
    def assistant_reply(self, call: AssistantCall) -> RemoteAssistant:
        return self._answer(call, self.reply)


@final
@dataclass
class RecordingAiStore(AiOutputStorePort):
    """Keeps every stored AI output, so a test can read what the backend wrote."""

    forecasts: list[ForecastRecord] = field(default_factory=list)
    risks: list[RiskRecord] = field(default_factory=list)
    summaries: list[SummaryRecord] = field(default_factory=list)
    replies: list[AssistantRecord] = field(default_factory=list)
    on_summary: Callable[[SummaryRecord], None] | None = None
    """Where a stored summary is also visible to the reads, as in the database."""
    on_reply: Callable[[AssistantRecord], None] | None = None
    """Where a stored reply joins the conversation history, as in the database."""

    @override
    def store_forecast(
        self, record: ForecastRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        self.forecasts.append(record)

    @override
    def store_risk(
        self, record: RiskRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        self.risks.append(record)

    @override
    def store_summary(
        self, record: SummaryRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        self.summaries.append(record)
        if self.on_summary is not None:
            self.on_summary(record)

    @override
    def store_assistant_reply(
        self, record: AssistantRecord, *, request_id: str | None, occurred_at: datetime
    ) -> None:
        self.replies.append(record)
        if self.on_reply is not None:
            self.on_reply(record)


def _page[T](rows: Sequence[T], key: Callable[[T], UUID], page: PageRequest) -> Page[T]:
    """The rows newest first (by id), after the cursor, cut like the repositories do."""
    ordered = sorted(rows, key=key, reverse=True)
    if page.after is not None:
        ordered = [row for row in ordered if key(row) < page.after]
    return build_page(ordered[: page.limit + 1], limit=page.limit, key=key)


@final
@dataclass
class FakePatternFindings(PatternFindingReadPort):
    """The findings, and the dismissals the reviews port records against them."""

    items: list[PatternFindingView] = field(default_factory=list)
    dismissals: dict[UUID, tuple[datetime, UUID]] = field(default_factory=dict)

    def _view(self, item: PatternFindingView) -> PatternFindingView:
        dismissed = self.dismissals.get(item.finding_id)
        if dismissed is None:
            return item
        return replace(item, dismissed_at=dismissed[0], dismissed_by=dismissed[1])

    @override
    def list_for_patient(
        self, patient_id: UUID, page: PageRequest
    ) -> Page[PatternFindingView]:
        rows = [item for item in self.items if item.patient_id == patient_id]
        return _page(
            [self._view(item) for item in rows], lambda item: item.finding_id, page
        )

    @override
    def get_for_patient(
        self, patient_id: UUID, finding_id: UUID
    ) -> PatternFindingView | None:
        for item in self.items:
            if item.finding_id == finding_id and item.patient_id == patient_id:
                return self._view(item)
        return None


@final
@dataclass
class FakePatternFindingReviews(PatternFindingReviewPort):
    """Appends dismissals and refuses a second one, as ``UNIQUE(finding_id)`` does."""

    findings: FakePatternFindings
    rows: list[FindingDismissal] = field(default_factory=list)

    @override
    def add(self, dismissal: FindingDismissal) -> None:
        if dismissal.finding_id in self.findings.dismissals:
            raise InvalidStateTransitionError("PATTERN_FINDING", "DISMISSED", "DISMISS")
        self.findings.dismissals[dismissal.finding_id] = (
            dismissal.reviewed_at,
            dismissal.reviewed_by,
        )
        self.rows.append(dismissal)


@final
@dataclass
class FakeDropoutRisks(DropoutRiskReadPort):
    items: list[DropoutRiskView] = field(default_factory=list)
    assigned: set[tuple[UUID, UUID]] = field(default_factory=set)

    @override
    def list_for_doctor(
        self, doctor_id: UUID, *, tier: RiskTier | None, page: PageRequest
    ) -> Page[DropoutRiskView]:
        rows = [
            item
            for item in self.items
            if (doctor_id, item.patient_id) in self.assigned
            and (tier is None or item.risk_tier is tier)
        ]
        return _page(rows, lambda item: item.patient_id, page)


@final
@dataclass
class FakeClinicDropoutRisks(DropoutRiskClinicReadPort):
    """The administrative list of the clinic (``ai.dropout_risk_list()``)."""

    items: list[DropoutRiskView] = field(default_factory=list)

    @override
    def list_for_clinic(
        self, *, tier: RiskTier | None, page: PageRequest
    ) -> Page[DropoutRiskView]:
        rows = [item for item in self.items if tier is None or item.risk_tier is tier]
        return _page(rows, lambda item: item.patient_id, page)


@final
@dataclass
class FakeSummaryReads(ClinicalSummaryReadPort):
    items: dict[UUID, ClinicalSummaryView] = field(default_factory=dict)

    def remember(self, record: SummaryRecord) -> None:
        """Make a stored summary readable, as the row is in the table."""
        output = record.output
        self.items[output.summary_id] = ClinicalSummaryView(
            summary_id=output.summary_id,
            patient_id=record.patient_id,
            period_start=output.period_start,
            period_end=output.period_end,
            summary_text=output.summary_text,
            sections=output.sections,
            numeric_check_matched=output.numeric_check_matched,
            model_version=output.model_version,
            is_fallback=output.is_fallback,
            fallback_reason=None
            if output.fallback_reason is None
            else output.fallback_reason.value,
            generated_at=output.generated_at,
        )

    @override
    def get(self, summary_id: UUID) -> ClinicalSummaryView | None:
        return self.items.get(summary_id)


def _evaluation_page(
    items: Sequence[AiEvaluationView], filters: AiEvaluationFilter, page: PageRequest
) -> Page[AiEvaluationView]:
    rows = [
        item
        for item in items
        if (filters.use_case is None or item.use_case == filters.use_case)
        and (
            filters.model_version is None or item.model_version == filters.model_version
        )
    ]
    return _page(rows, lambda item: item.evaluation_id, page)


@final
@dataclass
class FakeEvaluations(AiEvaluationReadPort):
    items: list[AiEvaluationView] = field(default_factory=list)

    @override
    def list(
        self, filters: AiEvaluationFilter, page: PageRequest
    ) -> Page[AiEvaluationView]:
        return _evaluation_page(self.items, filters, page)


@final
@dataclass
class FakePlatformEvaluations(PlatformAiEvaluationReadPort):
    """Every clinic's evaluations (``ai.platform_ai_evaluations()``)."""

    items: list[AiEvaluationView] = field(default_factory=list)

    @override
    def list(
        self, filters: AiEvaluationFilter, page: PageRequest
    ) -> Page[AiEvaluationView]:
        return _evaluation_page(self.items, filters, page)


@final
@dataclass
class FakePatientProfiles(PatientAiProfilePort):
    codes: dict[UUID, str] = field(default_factory=dict)

    @override
    def diabetes_type(self, patient_id: UUID) -> str | None:
        return self.codes.get(patient_id)


@final
@dataclass
class FakeConversations(AssistantConversationPort):
    """Turns of every patient: ``(patient, conversation, sender, text, sent_at)``."""

    rows: list[tuple[UUID, UUID, str, str, datetime]] = field(default_factory=list)

    @override
    def history(
        self, patient_id: UUID, conversation_id: UUID, *, limit: int
    ) -> tuple[AssistantTurn, ...]:
        turns = [
            AssistantTurn(sender=sender, text=text)
            for owner, conversation, sender, text, _ in sorted(
                self.rows, key=lambda row: row[4]
            )
            if owner == patient_id and conversation == conversation_id
        ]
        return tuple(turns[-limit:])

    @override
    def add_patient_message(
        self,
        *,
        clinic_id: UUID,
        patient_id: UUID,
        conversation_id: UUID,
        content: str,
        sent_at: datetime,
    ) -> UUID:
        del clinic_id
        self.rows.append((patient_id, conversation_id, "PATIENT", content, sent_at))
        return conversation_id


@final
@dataclass
class FakeKnowledge(ApprovedKnowledgePort):
    """Approved fragments; a keyword matches when it occurs in the title or the text."""

    fragments: list[ApprovedFragment] = field(default_factory=list)

    @override
    def search(
        self, keywords: Sequence[str], *, limit: int, max_chars: int
    ) -> tuple[ApprovedFragment, ...]:
        found = [
            ApprovedFragment(
                doc_id=item.doc_id, title=item.title, text=item.text[:max_chars]
            )
            for item in self.fragments
            if any(
                word in item.title.lower() or word in item.text.lower()
                for word in keywords
            )
        ]
        return tuple(found[:limit])


@final
class AiWorld:
    """Every AI port of one test, with the real proxy over the test doubles."""

    def __init__(self, *, clock: Any, ids: Any, app_hmac_key: str) -> None:
        self.service = ScriptedAiService()
        self.summary_reads = FakeSummaryReads()
        self.store = RecordingAiStore(
            on_summary=self.summary_reads.remember,
            on_reply=self._remember_reply,
        )
        self.findings = FakePatternFindings()
        self.pattern_reviews = FakePatternFindingReviews(self.findings)
        self.dropout = FakeDropoutRisks()
        self.dropout_clinic = FakeClinicDropoutRisks()
        self.evaluations = FakeEvaluations()
        self.platform_evaluations = FakePlatformEvaluations()
        self.profiles = FakePatientProfiles()
        self.conversations = FakeConversations()
        self.knowledge = FakeKnowledge()
        messages = MessageCatalog.load_spanish()
        self.proxy = RemoteAiServiceProxy(
            service=self.service,
            breaker=CircuitBreaker(
                CircuitPolicy(failure_threshold=1_000, open_for=timedelta(seconds=30))
            ),
            enabled=True,
            pseudonymizer=HmacPseudonymizer(
                SubkeyHasher(decode_key(app_hmac_key), subkey=Subkey.SUBJECT_REF)
            ),
            store=self.store,
            clock=clock,
            ids=ids,
            risk_strategy=RuleBasedRiskStrategy(),
            messages=messages,
        )

    def _remember_reply(self, record: AssistantRecord) -> None:
        output = record.output
        self.conversations.rows.append(
            (
                record.patient_id,
                output.conversation_id,
                "ASSISTANT",
                output.reply_text,
                output.generated_at,
            )
        )

    def adapters(
        self,
        *,
        recommendations: RecommendationRepositoryPort,
        drafts: OpenPlanDraftPort,
    ) -> AiAdapters:
        return AiAdapters(
            forecasts=self.proxy,
            recommendations=recommendations,
            drafts=drafts,
            risks=self.proxy,
            summaries=self.proxy,
            assistant=self.proxy,
            findings=self.findings,
            pattern_reviews=self.pattern_reviews,
            dropout=self.dropout,
            dropout_clinic=self.dropout_clinic,
            summary_reads=self.summary_reads,
            evaluations=self.evaluations,
            platform_evaluations=self.platform_evaluations,
            patient_profiles=self.profiles,
            conversations=self.conversations,
            knowledge=self.knowledge,
        )


__all__ = [
    "AiWorld",
    "FakeClinicDropoutRisks",
    "FakeConversations",
    "FakeDropoutRisks",
    "FakeEvaluations",
    "FakeKnowledge",
    "FakePatientProfiles",
    "FakePatternFindingReviews",
    "FakePatternFindings",
    "FakePlatformEvaluations",
    "FakeSummaryReads",
    "RecordingAiStore",
    "ScriptedAiService",
]
