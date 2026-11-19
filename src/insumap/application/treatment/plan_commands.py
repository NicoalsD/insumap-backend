"""Decisions about treatment plans (P13, P09): create, edit, activate, version, restore.

Every write runs through ``CommandGuard``: one transaction, the handler, and the
audit row of the command. The patient is checked by ``AssignedPatientGate``
(P11 behind P09), so an unassigned patient answers ``404`` before anything is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.application.treatment.inputs import PlanContentInput
from insumap.application.treatment.ports import (
    ProtocolTemplateRepositoryPort,
    TargetProfileLookupPort,
    TreatmentPlanRepositoryPort,
    TreatmentPlanSnapshotPort,
)
from insumap.application.treatment.snapshots import PlanSnapshotCaretaker
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.treatment.builder import TreatmentPlanBuilder
from insumap.domain.treatment.content import ItemSpec, PlanItem, ProtocolLimits
from insumap.domain.treatment.plan import MACHINE_NAME, TreatmentPlan
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

PLAN_ENTITY: Final = "TREATMENT_PLAN"
MANAGE: Final = PermissionCode.TREATMENT_PLANS_MANAGE


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateTreatmentPlanCommand(Command[TreatmentPlan]):
    """The doctor starts a plan for an assigned patient, from a template or not."""

    audit_action: ClassVar[str] = "TREATMENT_PLAN_CREATED"
    audit_entity_type: ClassVar[str] = PLAN_ENTITY

    patient_id: UUID
    template_id: UUID | None = None
    content: PlanContentInput | None = None

    @override
    def audit_subject(self, result: TreatmentPlan) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.plan_id,
            changed_fields=("items", "version", "template_id", "status"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateTreatmentPlanCommand(Command[TreatmentPlan]):
    """The doctor edits the draft of a plan; an active plan is never edited."""

    audit_action: ClassVar[str] = "TREATMENT_PLAN_UPDATED"
    audit_entity_type: ClassVar[str] = PLAN_ENTITY

    plan_id: UUID
    content: PlanContentInput

    @override
    def audit_subject(self, result: TreatmentPlan) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.plan_id,
            changed_fields=("items", "titration_rules", "notes"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivateTreatmentPlanCommand(Command[TreatmentPlan]):
    """Pattern: P13 Command. Activates a draft after the builder checks its invariants.

    The plan that was active is superseded first, so the one-active-plan rule
    holds at every statement of the transaction.
    """

    audit_action: ClassVar[str] = "TREATMENT_PLAN_ACTIVATED"
    audit_entity_type: ClassVar[str] = PLAN_ENTITY

    plan_id: UUID

    @override
    def audit_subject(self, result: TreatmentPlan) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.plan_id,
            changed_fields=("status", "activated_by", "activated_at"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateTreatmentPlanVersionCommand(Command[TreatmentPlan]):
    """The doctor opens a new draft from the active plan (P05)."""

    audit_action: ClassVar[str] = "TREATMENT_PLAN_VERSIONED"
    audit_entity_type: ClassVar[str] = PLAN_ENTITY

    plan_id: UUID

    @override
    def audit_subject(self, result: TreatmentPlan) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.plan_id,
            changed_fields=("version", "previous_plan_id", "status"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RestoreTreatmentPlanCommand(Command[TreatmentPlan]):
    """The doctor brings back the content of a photo as a new draft (P16 and P05)."""

    audit_action: ClassVar[str] = "TREATMENT_PLAN_RESTORED"
    audit_entity_type: ClassVar[str] = PLAN_ENTITY

    plan_id: UUID
    snapshot_id: UUID

    @override
    def audit_subject(self, result: TreatmentPlan) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.plan_id,
            changed_fields=("items", "version", "status"),
        )


def _clinic(actor: Actor) -> UUID:
    if actor.clinic_id is None:
        raise ResourceNotFoundError
    return actor.clinic_id


def _plan_items(ids: IdGenerator, specs: tuple[ItemSpec, ...]) -> tuple[PlanItem, ...]:
    return tuple(PlanItem.of(ids.new_id(), spec) for spec in specs)


@final
class _AssignedPlan:
    """Loads a plan the session may change: permission first, then ``404``, then P11."""

    def __init__(self, plans: TreatmentPlanRepositoryPort, gate: AssignedPatientGate):
        self._plans = plans
        self._gate = gate

    def load(self, actor: Actor, plan_id: UUID) -> TreatmentPlan:
        actor.require(MANAGE)
        plan = self._plans.get(plan_id)
        if plan is None:
            raise ResourceNotFoundError
        self._gate.enter(actor, MANAGE, plan.patient_id, DataResource.TREATMENT_PLAN)
        return plan


@final
class _TargetOf:
    """The goals profile of a new plan: the template's default, else the patient's."""

    def __init__(self, targets: TargetProfileLookupPort) -> None:
        self._targets = targets

    def for_patient(self, patient_id: UUID) -> UUID:
        profile = self._targets.profile_id_for(patient_id)
        if profile is None:
            # A clinic without goals is a setup error, not something the user fixes.
            raise InsumapError(ErrorCode.INTERNAL_ERROR)
        return profile


@final
class CreateTreatmentPlanCommandHandler(
    CommandHandler[CreateTreatmentPlanCommand, TreatmentPlan]
):
    """Creates a draft; a template is cloned in depth, then personalised if given."""

    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        plans: TreatmentPlanRepositoryPort,
        templates: ProtocolTemplateRepositoryPort,
        targets: TargetProfileLookupPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._plans = plans
        self._templates = templates
        self._targets = _TargetOf(targets)
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateTreatmentPlanCommand) -> TreatmentPlan:
        actor = command.actor
        actor.require(MANAGE)
        clinic_id = _clinic(actor)
        patient_id = self._gate.enter(
            actor, MANAGE, command.patient_id, DataResource.TREATMENT_PLAN
        )
        at = self._clock.now()
        version = self._plans.highest_version(patient_id) + 1
        plan_id = self._ids.new_id()
        if command.template_id is None:
            content = command.content or PlanContentInput(items=())
            plan = TreatmentPlan.draft(
                plan_id=plan_id,
                clinic_id=clinic_id,
                patient_id=patient_id,
                version=version,
                target_profile_id=self._targets.for_patient(patient_id),
                created_by=actor.user_id,
                at=at,
                items=_plan_items(self._ids, content.items),
                titration_rules=content.titration_rules,
                notes=content.notes,
            )
        else:
            template = self._templates.get(command.template_id)
            if template is None:
                raise ResourceNotFoundError
            profile = template.default_target_profile_id or self._targets.for_patient(
                patient_id
            )
            item_ids = tuple(self._ids.new_id() for _ in template.content.items)
            plan = template.clone_for_patient(
                plan_id=plan_id,
                clinic_id=clinic_id,
                patient_id=patient_id,
                target_profile_id=profile,
                version=version,
                item_ids=item_ids,
                created_by=actor.user_id,
                at=at,
            )
            if command.content is not None:
                plan = plan.with_content(
                    items=_plan_items(self._ids, command.content.items),
                    titration_rules=command.content.titration_rules,
                    notes=command.content.notes,
                    at=at,
                )
        self._plans.insert(plan)
        return plan


@final
class UpdateTreatmentPlanCommandHandler(
    CommandHandler[UpdateTreatmentPlanCommand, TreatmentPlan]
):
    """Replaces the content of a draft, after a photo of the draft (P16)."""

    def __init__(
        self,
        *,
        scope: _AssignedPlan,
        plans: TreatmentPlanRepositoryPort,
        snapshots: PlanSnapshotCaretaker,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._scope = scope
        self._plans = plans
        self._snapshots = snapshots
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: UpdateTreatmentPlanCommand) -> TreatmentPlan:
        actor = command.actor
        plan = self._scope.load(actor, command.plan_id)
        at = self._clock.now()
        edited = plan.with_content(
            items=_plan_items(self._ids, command.content.items),
            titration_rules=command.content.titration_rules,
            notes=command.content.notes,
            at=at,
        )
        self._snapshots.before_change(plan, taken_by=actor.user_id, at=at)
        self._plans.update(edited)
        self._plans.replace_items(edited)
        return edited


@final
class ActivateTreatmentPlanCommandHandler(
    CommandHandler[ActivateTreatmentPlanCommand, TreatmentPlan]
):
    """Pattern: P13 Command. Checks the draft, then supersedes the active plan."""

    def __init__(
        self,
        *,
        scope: _AssignedPlan,
        plans: TreatmentPlanRepositoryPort,
        templates: ProtocolTemplateRepositoryPort,
        snapshots: PlanSnapshotCaretaker,
        clock: Clock,
    ) -> None:
        self._scope = scope
        self._plans = plans
        self._templates = templates
        self._snapshots = snapshots
        self._clock = clock

    @override
    def handle(self, command: ActivateTreatmentPlanCommand) -> TreatmentPlan:
        actor = command.actor
        plan = self._scope.load(actor, command.plan_id)
        if not plan.is_draft:
            raise InvalidStateTransitionError(
                MACHINE_NAME, plan.status.value, "activate"
            )
        validated = TreatmentPlanBuilder(plan, limits=self._limits_of(plan)).build()
        at = self._clock.now()
        current = self._plans.active_for(plan.patient_id)
        if current is not None:
            self._snapshots.before_change(current, taken_by=actor.user_id, at=at)
            self._plans.update(current.supersede(at=at))
        self._snapshots.before_change(plan, taken_by=actor.user_id, at=at)
        activated = validated.activate(by=actor.user_id, at=at)
        self._plans.update(activated)
        return activated

    def _limits_of(self, plan: TreatmentPlan) -> ProtocolLimits | None:
        if plan.template_id is None:
            return None
        template = self._templates.get(plan.template_id)
        if template is None:
            raise InsumapError(ErrorCode.INTERNAL_ERROR)
        return template.content.limits


@final
class CreateTreatmentPlanVersionCommandHandler(
    CommandHandler[CreateTreatmentPlanVersionCommand, TreatmentPlan]
):
    """Opens the next draft from the active plan; the active plan does not change."""

    def __init__(
        self,
        *,
        scope: _AssignedPlan,
        plans: TreatmentPlanRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._scope = scope
        self._plans = plans
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateTreatmentPlanVersionCommand) -> TreatmentPlan:
        actor = command.actor
        plan = self._scope.load(actor, command.plan_id)
        version = self._plans.highest_version(plan.patient_id) + 1
        draft = plan.open_new_version(
            new_plan_id=self._ids.new_id(),
            item_ids=tuple(self._ids.new_id() for _ in plan.items),
            version=version,
            created_by=actor.user_id,
            at=self._clock.now(),
        )
        self._plans.insert(draft)
        return draft


@final
class RestoreTreatmentPlanCommandHandler(
    CommandHandler[RestoreTreatmentPlanCommand, TreatmentPlan]
):
    """Rebuilds a photo and stores it as a new draft; no version is rewritten (P16)."""

    def __init__(
        self,
        *,
        scope: _AssignedPlan,
        plans: TreatmentPlanRepositoryPort,
        snapshots: TreatmentPlanSnapshotPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._scope = scope
        self._plans = plans
        self._snapshots = snapshots
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: RestoreTreatmentPlanCommand) -> TreatmentPlan:
        actor = command.actor
        plan = self._scope.load(actor, command.plan_id)
        stored = self._snapshots.get(command.snapshot_id, plan.plan_id)
        if stored is None:
            raise ResourceNotFoundError
        restored = TreatmentPlan.from_memento(stored.memento)
        draft = restored.copy_for_new_version(
            new_plan_id=self._ids.new_id(),
            item_ids=tuple(self._ids.new_id() for _ in restored.items),
            version=self._plans.highest_version(plan.patient_id) + 1,
            created_by=actor.user_id,
            at=self._clock.now(),
        )
        self._plans.insert(draft)
        return draft


def make_scope(
    plans: TreatmentPlanRepositoryPort, gate: AssignedPatientGate
) -> _AssignedPlan:
    """The loader the plan handlers share; built once by the container."""
    return _AssignedPlan(plans, gate)
