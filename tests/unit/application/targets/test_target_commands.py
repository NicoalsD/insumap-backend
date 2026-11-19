"""Target profile commands (P13) over in-memory doubles: rules, audit and states."""

from decimal import Decimal
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.common.actor import Actor
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.application.targets.commands import (
    AssignTargetProfileCommand,
    AssignTargetProfileCommandHandler,
    CreateTargetProfileCommand,
    CreateTargetProfileCommandHandler,
    CreateTargetProfileVersionCommand,
    CreateTargetProfileVersionCommandHandler,
)
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.metrics.target_profile_version import (
    ACTIVE,
    RETIRED,
    TargetProfileInvariantError,
)
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds
from tests.support.monitoring_factories import PATIENT_ID
from tests.support.monitoring_fakes import DOCTOR_ID, FakePatientRecords
from tests.support.targets_fakes import (
    CLINIC_ID,
    NOW,
    FakeTargetAssignments,
    FakeTargetCatalog,
    clinic_profile,
    default_values,
)

ADMIN = UUID(int=3)
PROFILE = UUID(int=500)
SEED = UUID(int=501)
OTHER_CLINIC_PROFILE = UUID(int=502)
REASON = "Ajuste aprobado por el comité de la clínica"
MANAGE = frozenset({PermissionCode.TARGET_PROFILES_MANAGE})
ASSIGN = frozenset({PermissionCode.TARGET_PROFILES_ASSIGN})


def actor(user: UUID, role: Role, permissions: frozenset[PermissionCode]) -> Actor:
    return Actor(
        user_id=user,
        clinic_id=CLINIC_ID,
        role=role,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


class World:
    def __init__(self) -> None:
        self.catalog = FakeTargetCatalog(
            clinic_profile(PROFILE),
            clinic_profile(SEED, clinic_id=None, code="SEED_TARGETS"),
            clinic_profile(OTHER_CLINIC_PROFILE, clinic_id=UUID(int=77), code="OTHER"),
        )
        self.assignments = FakeTargetAssignments()
        self.patients = FakePatientRecords()
        self.ids = FakeIds()
        self.clock = FixedClock(NOW)
        self.audit = InMemoryAuditLog()

    def create(self) -> CreateTargetProfileCommandHandler:
        return CreateTargetProfileCommandHandler(
            catalog=self.catalog, ids=self.ids, clock=self.clock
        )

    def version(self) -> CreateTargetProfileVersionCommandHandler:
        return CreateTargetProfileVersionCommandHandler(
            catalog=self.catalog, ids=self.ids, clock=self.clock
        )

    def assign(self) -> AssignTargetProfileCommandHandler:
        return AssignTargetProfileCommandHandler(
            gate=AssignedPatientGate(self.patients),
            catalog=self.catalog,
            assignments=self.assignments,
            ids=self.ids,
            clock=self.clock,
        )


@pytest.fixture
def world() -> World:
    return World()


def test_create_profile_is_active_version_one_and_audited(world: World) -> None:
    admin = actor(ADMIN, Role.CLINIC_ADMIN, MANAGE)
    command = CreateTargetProfileCommand(
        actor=admin, code="CLINIC_NEW", values=default_values()
    )

    created = AuditingCommandHandler(world.create(), world.audit, world.clock).handle(
        command
    )

    assert created.version == 1
    assert created.status == ACTIVE
    assert created.clinic_id == CLINIC_ID
    assert created.activated_at == NOW
    assert [e.action for e in world.audit.entries] == ["TARGET_PROFILE_CREATED"]


def test_create_profile_refuses_a_code_the_clinic_already_uses(world: World) -> None:
    command = CreateTargetProfileCommand(
        actor=actor(ADMIN, Role.CLINIC_ADMIN, MANAGE),
        code="CLINIC_TARGETS",
        values=default_values(),
    )

    with pytest.raises(ConflictError):
        world.create().handle(command)


def test_create_profile_lists_every_broken_rule_and_writes_nothing(
    world: World,
) -> None:
    command = CreateTargetProfileCommand(
        actor=actor(ADMIN, Role.CLINIC_ADMIN, MANAGE),
        code="CLINIC_BAD",
        values=default_values(range_high_mg_dl=Decimal("60.0")),
    )

    with pytest.raises(TargetProfileInvariantError) as raised:
        world.create().handle(command)

    assert raised.value.code is ErrorCode.VALIDATION_ERROR
    assert not world.catalog.code_exists(CLINIC_ID, "CLINIC_BAD")


def test_create_profile_needs_the_manage_permission(world: World) -> None:
    command = CreateTargetProfileCommand(
        actor=actor(DOCTOR_ID, Role.DOCTOR, ASSIGN),
        code="CLINIC_NEW",
        values=default_values(),
    )

    with pytest.raises(PermissionDeniedError):
        world.create().handle(command)


def test_version_retires_the_active_one_and_inserts_the_next(world: World) -> None:
    command = CreateTargetProfileVersionCommand(
        actor=actor(ADMIN, Role.CLINIC_ADMIN, MANAGE),
        profile_id=PROFILE,
        changes={"tir_min_pct": Decimal("75.00")},
        change_reason=REASON,
    )

    new = world.version().handle(command)

    assert new.version == 2
    assert new.status == ACTIVE
    assert new.values.tir_min_pct == Decimal("75.00")
    assert world.catalog.profiles[PROFILE].status == RETIRED
    assert world.catalog.active_of_clinic(CLINIC_ID, "CLINIC_TARGETS") == new


def test_version_that_breaks_the_profile_keeps_the_active_one(world: World) -> None:
    command = CreateTargetProfileVersionCommand(
        actor=actor(ADMIN, Role.CLINIC_ADMIN, MANAGE),
        profile_id=PROFILE,
        changes={"very_high_mg_dl": Decimal("150.0")},
        change_reason=REASON,
    )

    with pytest.raises(TargetProfileInvariantError):
        world.version().handle(command)

    assert world.catalog.profiles[PROFILE].status == ACTIVE


def test_a_seed_is_never_versioned_by_a_clinic(world: World) -> None:
    command = CreateTargetProfileVersionCommand(
        actor=actor(ADMIN, Role.CLINIC_ADMIN, MANAGE),
        profile_id=SEED,
        changes={"cv_max_pct": Decimal("30.00")},
        change_reason=REASON,
    )

    with pytest.raises(ResourceNotFoundError):
        world.version().handle(command)


def test_assign_opens_the_assignment_and_ends_the_previous_one(world: World) -> None:
    doctor = actor(DOCTOR_ID, Role.DOCTOR, ASSIGN)
    world.catalog.insert(clinic_profile(UUID(int=600), code="SECOND", version=1))
    first = world.assign().handle(
        AssignTargetProfileCommand(
            actor=doctor, patient_id=PATIENT_ID, target_profile_id=PROFILE
        )
    )

    second = world.assign().handle(
        AssignTargetProfileCommand(
            actor=doctor, patient_id=PATIENT_ID, target_profile_id=UUID(int=600)
        )
    )

    assert first.target_profile_id == PROFILE
    assert second.target_profile_id == UUID(int=600)
    assert [r.ended_at is None for r in world.assignments.rows] == [False, True]
    assert world.patients.reads[-1][2].value == "CARE"


def test_assign_the_same_profile_again_changes_nothing(world: World) -> None:
    doctor = actor(DOCTOR_ID, Role.DOCTOR, ASSIGN)
    command = AssignTargetProfileCommand(
        actor=doctor, patient_id=PATIENT_ID, target_profile_id=PROFILE
    )
    first = world.assign().handle(command)

    again = world.assign().handle(command)

    assert again == first
    assert len(world.assignments.rows) == 1


def test_assign_a_retired_profile_is_a_state_error(world: World) -> None:
    world.catalog.retire(PROFILE)

    with pytest.raises(InvalidStateTransitionError):
        world.assign().handle(
            AssignTargetProfileCommand(
                actor=actor(DOCTOR_ID, Role.DOCTOR, ASSIGN),
                patient_id=PATIENT_ID,
                target_profile_id=PROFILE,
            )
        )


def test_assign_a_profile_of_another_clinic_is_not_found(world: World) -> None:
    with pytest.raises(ResourceNotFoundError):
        world.assign().handle(
            AssignTargetProfileCommand(
                actor=actor(DOCTOR_ID, Role.DOCTOR, ASSIGN),
                patient_id=PATIENT_ID,
                target_profile_id=OTHER_CLINIC_PROFILE,
            )
        )


def test_assign_an_unassigned_patient_is_not_found(world: World) -> None:
    stranger = UUID(int=0xBEEF)

    with pytest.raises(InsumapError) as raised:
        world.assign().handle(
            AssignTargetProfileCommand(
                actor=actor(DOCTOR_ID, Role.DOCTOR, ASSIGN),
                patient_id=stranger,
                target_profile_id=PROFILE,
            )
        )
    assert raised.value.code is ErrorCode.NOT_FOUND


def test_assign_needs_the_assign_permission(world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        world.assign().handle(
            AssignTargetProfileCommand(
                actor=actor(DOCTOR_ID, Role.DOCTOR, frozenset()),
                patient_id=PATIENT_ID,
                target_profile_id=PROFILE,
            )
        )


def test_assign_is_audited_with_the_assignment_id(world: World) -> None:
    handler = AuditingCommandHandler(world.assign(), world.audit, world.clock)

    assignment = handler.handle(
        AssignTargetProfileCommand(
            actor=actor(DOCTOR_ID, Role.DOCTOR, ASSIGN),
            patient_id=PATIENT_ID,
            target_profile_id=PROFILE,
        )
    )

    [entry] = world.audit.entries
    assert entry.action == "TARGET_PROFILE_ASSIGNED"
    assert entry.entity_id == assignment.id
    assert entry.changed_fields == ("target_profile_id",)
    assert assignment.patient_id == PATIENT_ID
