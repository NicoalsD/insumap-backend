"""The world the treatment use cases run in: doubles, actors and fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import InMemoryCommandBus, bind
from insumap.application.common.actor import Actor
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.treatment.plan_commands import (
    ActivateTreatmentPlanCommand,
    ActivateTreatmentPlanCommandHandler,
    CreateTreatmentPlanCommandHandler,
    CreateTreatmentPlanVersionCommandHandler,
    RestoreTreatmentPlanCommandHandler,
    UpdateTreatmentPlanCommandHandler,
    make_scope,
)
from insumap.application.treatment.snapshots import PlanSnapshotCaretaker
from insumap.application.treatment.template_commands import (
    CreateProtocolTemplateCommandHandler,
    CreateProtocolTemplateVersionCommandHandler,
    RetireProtocolTemplateCommandHandler,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.treatment.content import ProtocolLimits, TemplateContent
from insumap.domain.treatment.plan import TreatmentPlan
from insumap.domain.treatment.template import ProtocolTemplate, TemplateStatus
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeUnitOfWorkPort
from tests.support.monitoring_fakes import FakeConsentsGate
from tests.support.treatment_fakes import (
    FakeAssignments,
    FakePlans,
    FakeSnapshots,
    FakeTargets,
    FakeTemplates,
    SequentialIds,
)
from tests.unit.domain.treatment.factories import (
    AT,
    CLINIC,
    DOCTOR,
    PATIENT,
    TARGET,
    TEMPLATE,
    insulin,
    measure,
    template_content,
)

PATIENT_USER = UUID(int=50)
OTHER_DOCTOR = UUID(int=4)
DOCTOR_PERMISSIONS = frozenset(
    {PermissionCode.TREATMENT_PLANS_MANAGE, PermissionCode.PROTOCOL_TEMPLATES_READ}
)
"""What the seed grants a DOCTOR (``insumap-database`` seed of the roles)."""
PATIENT_PERMISSIONS = frozenset({PermissionCode.TREATMENT_PLANS_READ_OWN})
CLINIC_ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.PROTOCOL_TEMPLATES_MANAGE, PermissionCode.PROTOCOL_TEMPLATES_READ}
)


def doctor(
    user: UUID = DOCTOR, permissions: frozenset[PermissionCode] = DOCTOR_PERMISSIONS
) -> Actor:
    return Actor(
        user_id=user,
        clinic_id=CLINIC,
        role=Role.DOCTOR,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


def admin(
    permissions: frozenset[PermissionCode] = CLINIC_ADMIN_PERMISSIONS,
) -> Actor:
    return Actor(
        user_id=UUID(int=3),
        clinic_id=CLINIC,
        role=Role.CLINIC_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


def patient_actor() -> Actor:
    return Actor(
        user_id=PATIENT_USER,
        clinic_id=CLINIC,
        role=Role.PATIENT,
        permissions=PATIENT_PERMISSIONS,
        patient_id=PATIENT,
    )


def template_row(
    *,
    template_id: UUID = TEMPLATE,
    code: str = "BASAL_BOLO",
    version: int = 1,
    status: TemplateStatus = TemplateStatus.ACTIVE,
    content: TemplateContent | None = None,
    clinic: UUID | None = CLINIC,
    default_profile: UUID | None = None,
) -> ProtocolTemplate:
    return ProtocolTemplate(
        template_id=template_id,
        clinic_id=clinic,
        code=code,
        name="Basal-bolo adulto",
        version=version,
        status=status,
        content=content or template_content(insulin("Basal"), measure()),
        created_by=DOCTOR,
        created_at=AT,
        default_target_profile_id=default_profile,
    )


def limited(max_dose: str) -> TemplateContent:
    return TemplateContent(
        items=(insulin("Basal"),),
        limits=ProtocolLimits(max_dose_units=Decimal(max_dose)),
    )


class World:
    """Every port of the treatment use cases, over in-memory doubles."""

    def __init__(
        self,
        *,
        plans: tuple[TreatmentPlan, ...] = (),
        templates: tuple[ProtocolTemplate, ...] = (),
        assigned: tuple[tuple[UUID, UUID], ...] = ((DOCTOR, PATIENT),),
        target: UUID | None = TARGET,
        accepted: bool = True,
    ) -> None:
        self.plans = FakePlans(*plans)
        self.templates = FakeTemplates(*templates)
        self.snapshots = FakeSnapshots()
        self.assignments = FakeAssignments(*assigned)
        self.targets = FakeTargets(target)
        self.consents = FakeConsentsGate(accepted=accepted)
        self.gate = AssignedPatientGate(self.assignments)
        self.own_gate = OwnPatientGate(self.consents)
        self.uow = FakeUnitOfWorkPort()
        self.ids = SequentialIds()
        self.clock = FixedClock(AT)
        self.caretaker = PlanSnapshotCaretaker(self.snapshots)
        self.scope = make_scope(self.plans, self.gate)
        self.audit = InMemoryAuditLog()
        self.create_plan = CreateTreatmentPlanCommandHandler(
            gate=self.gate,
            plans=self.plans,
            templates=self.templates,
            targets=self.targets,
            ids=self.ids,
            clock=self.clock,
        )
        self.update_plan = UpdateTreatmentPlanCommandHandler(
            scope=self.scope,
            plans=self.plans,
            snapshots=self.caretaker,
            ids=self.ids,
            clock=self.clock,
        )
        self.activate = ActivateTreatmentPlanCommandHandler(
            scope=self.scope,
            plans=self.plans,
            templates=self.templates,
            snapshots=self.caretaker,
            clock=self.clock,
        )
        self.new_version = CreateTreatmentPlanVersionCommandHandler(
            scope=self.scope, plans=self.plans, ids=self.ids, clock=self.clock
        )
        self.restore = RestoreTreatmentPlanCommandHandler(
            scope=self.scope,
            plans=self.plans,
            snapshots=self.snapshots,
            ids=self.ids,
            clock=self.clock,
        )
        self.create_template = CreateProtocolTemplateCommandHandler(
            templates=self.templates, ids=self.ids, clock=self.clock
        )
        self.version_template = CreateProtocolTemplateVersionCommandHandler(
            templates=self.templates, ids=self.ids, clock=self.clock
        )
        self.retire_template = RetireProtocolTemplateCommandHandler(
            templates=self.templates
        )

    def bus(self) -> InMemoryCommandBus:
        """The command bus with every handler behind the audit decorator (P09)."""
        audited = AuditingCommandHandler(self.activate, self.audit, self.clock)
        return InMemoryCommandBus(
            [bind(ActivateTreatmentPlanCommand, audited)],
            required=(ActivateTreatmentPlanCommand,),
        )


def utc(day: int) -> datetime:
    return datetime(2026, 11, day, 9, 0, tzinfo=UTC)
