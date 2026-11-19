"""Doctor decisions on recommendations (P13): approve, modify or reject."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.ai.recommendations import (
    OpenPlanDraftPort,
    RecommendationRepositoryPort,
)
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.ids import IdGenerator
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.ai.events import RecommendationApproved
from insumap.domain.ai.recommendation import Recommendation
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

RECOMMENDATION_ENTITY = "RECOMMENDATION"
DECISION_FIELDS = ("status", "decided_by", "decided_at")
MODIFIED_FIELDS = ("status", "suggestion", "decided_by", "decided_at")


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecommendationDecision:
    """What a decision returns: the recommendation and, if one was opened, its draft."""

    recommendation: Recommendation
    draft_plan_id: UUID | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ApproveRecommendationCommand(Command[RecommendationDecision]):
    """The doctor accepts the proposal as it is."""

    audit_action: ClassVar[str] = "RECOMMENDATION_APPROVED"
    audit_entity_type: ClassVar[str] = RECOMMENDATION_ENTITY

    recommendation_id: UUID

    @override
    def audit_subject(self, result: RecommendationDecision) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.recommendation.recommendation_id,
            changed_fields=DECISION_FIELDS,
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ModifyRecommendationCommand(Command[RecommendationDecision]):
    """The doctor changes the proposal; the reason is mandatory."""

    audit_action: ClassVar[str] = "RECOMMENDATION_MODIFIED"
    audit_entity_type: ClassVar[str] = RECOMMENDATION_ENTITY

    recommendation_id: UUID
    modified_proposal: Mapping[str, Any]
    reason: str

    @override
    def audit_subject(self, result: RecommendationDecision) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.recommendation.recommendation_id,
            reason=self.reason.strip(),
            changed_fields=MODIFIED_FIELDS,
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RejectRecommendationCommand(Command[RecommendationDecision]):
    """The doctor refuses the proposal; the reason is mandatory."""

    audit_action: ClassVar[str] = "RECOMMENDATION_REJECTED"
    audit_entity_type: ClassVar[str] = RECOMMENDATION_ENTITY

    recommendation_id: UUID
    reason: str

    @override
    def audit_subject(self, result: RecommendationDecision) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.recommendation.recommendation_id,
            reason=self.reason.strip(),
            changed_fields=DECISION_FIELDS,
        )


class _DecisionHandler[C: Command[RecommendationDecision]](
    CommandHandler[C, RecommendationDecision]
):
    """The shared path of the three decisions: scope, transition, lock, history."""

    def __init__(
        self,
        *,
        recommendations: RecommendationRepositoryPort,
        assigned_gate: AssignedPatientGate,
        clock: Clock,
        current: CurrentUnitOfWork,
        ids: IdGenerator,
    ) -> None:
        self._recommendations = recommendations
        self._assigned = assigned_gate
        self._clock = clock
        self._current = current
        self._ids = ids

    def _load_for_decision(self, recommendation_id: UUID) -> Recommendation:
        recommendation = self._recommendations.get(recommendation_id)
        if recommendation is None:
            raise ResourceNotFoundError
        return recommendation

    def _save(self, moved: Recommendation, expected: int) -> None:
        if not self._recommendations.save(moved, expected_lock_version=expected):
            raise ConflictError("RECOMMENDATION_CHANGED")


@final
class ApproveRecommendationCommandHandler(
    _DecisionHandler[ApproveRecommendationCommand]
):
    """Approves, opens the plan draft and publishes the event after the commit."""

    def __init__(
        self,
        *,
        recommendations: RecommendationRepositoryPort,
        assigned_gate: AssignedPatientGate,
        drafts: OpenPlanDraftPort,
        clock: Clock,
        current: CurrentUnitOfWork,
        ids: IdGenerator,
    ) -> None:
        super().__init__(
            recommendations=recommendations,
            assigned_gate=assigned_gate,
            clock=clock,
            current=current,
            ids=ids,
        )
        self._drafts = drafts

    @override
    def handle(self, command: ApproveRecommendationCommand) -> RecommendationDecision:
        actor = command.actor
        actor.require(PermissionCode.RECOMMENDATIONS_DECIDE)
        current = self._load_for_decision(command.recommendation_id)
        self._assigned.enter(
            actor,
            PermissionCode.RECOMMENDATIONS_DECIDE,
            current.patient_id,
            DataResource.AI_OUTPUTS,
        )
        now = self._clock.now()
        moved, decision = current.approve(by=actor.user_id, at=now)
        self._save(moved, current.lock_version)
        self._recommendations.add_decision(moved, decision)
        draft = self._drafts.open_draft(moved.patient_id, by=actor.user_id, at=now)
        self._current.collect([_approved(moved, self._ids.new_id())])
        return RecommendationDecision(recommendation=moved, draft_plan_id=draft)


@final
class ModifyRecommendationCommandHandler(_DecisionHandler[ModifyRecommendationCommand]):
    """Accepts a change of the proposal, keeping the original and the change."""

    def __init__(
        self,
        *,
        recommendations: RecommendationRepositoryPort,
        assigned_gate: AssignedPatientGate,
        drafts: OpenPlanDraftPort,
        clock: Clock,
        current: CurrentUnitOfWork,
        ids: IdGenerator,
    ) -> None:
        super().__init__(
            recommendations=recommendations,
            assigned_gate=assigned_gate,
            clock=clock,
            current=current,
            ids=ids,
        )
        self._drafts = drafts

    @override
    def handle(self, command: ModifyRecommendationCommand) -> RecommendationDecision:
        actor = command.actor
        actor.require(PermissionCode.RECOMMENDATIONS_DECIDE)
        current = self._load_for_decision(command.recommendation_id)
        self._assigned.enter(
            actor,
            PermissionCode.RECOMMENDATIONS_DECIDE,
            current.patient_id,
            DataResource.AI_OUTPUTS,
        )
        now = self._clock.now()
        moved, decision = current.modify(
            modified=command.modified_proposal,
            reason=command.reason,
            by=actor.user_id,
            at=now,
        )
        self._save(moved, current.lock_version)
        self._recommendations.add_decision(moved, decision)
        draft = self._drafts.open_draft(moved.patient_id, by=actor.user_id, at=now)
        self._current.collect([_approved(moved, self._ids.new_id())])
        return RecommendationDecision(recommendation=moved, draft_plan_id=draft)


@final
class RejectRecommendationCommandHandler(_DecisionHandler[RejectRecommendationCommand]):
    """Refuses the proposal with the reason; no plan changes."""

    @override
    def handle(self, command: RejectRecommendationCommand) -> RecommendationDecision:
        actor = command.actor
        actor.require(PermissionCode.RECOMMENDATIONS_DECIDE)
        current = self._load_for_decision(command.recommendation_id)
        self._assigned.enter(
            actor,
            PermissionCode.RECOMMENDATIONS_DECIDE,
            current.patient_id,
            DataResource.AI_OUTPUTS,
        )
        moved, decision = current.reject(
            reason=command.reason, by=actor.user_id, at=self._clock.now()
        )
        self._save(moved, current.lock_version)
        self._recommendations.add_decision(moved, decision)
        return RecommendationDecision(recommendation=moved, draft_plan_id=None)


def _approved(recommendation: Recommendation, event_id: UUID) -> RecommendationApproved:
    """The event of an approval (approved as is, or with changes)."""
    return RecommendationApproved(
        event_id=event_id,
        occurred_at=recommendation.updated_at,
        recommendation_id=recommendation.recommendation_id,
        patient_id=recommendation.patient_id,
        clinic_id=recommendation.clinic_id,
        status=recommendation.status,
    )
