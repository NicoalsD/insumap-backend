"""AssignDoctorCommand (P13) and its siblings, behind the audit decorator (P09)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.access.ports import PatientDirectoryPort
from insumap.application.care_team.commands import (
    AssignDoctorCommand,
    AssignDoctorCommandHandler,
    EndAssignmentCommand,
    EndAssignmentCommandHandler,
    ReassignDoctorCommand,
    ReassignDoctorCommandHandler,
    SetPrimaryDoctorCommand,
    SetPrimaryDoctorCommandHandler,
)
from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import InMemoryCommandBus, bind
from insumap.application.common.actor import Actor
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.common.errors import (
    ConflictError,
    ReasonRequiredError,
    ResourceNotFoundError,
)
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.support.access_fakes import (
    CLINIC,
    DOCTOR,
    OTHER_DOCTOR,
    PATIENT,
    FakeDirectory,
)
from tests.support.care_team_fakes import FakeCareTeams, FakeStaff
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
ADMIN = UUID(int=3)
THIRD_DOCTOR = UUID(int=4)
REASON = "Cambio de turno de la médica"


def admin(*permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=CLINIC,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset(permissions or {PermissionCode.CARE_TEAM_ASSIGN}),
        requires_mfa=True,
        mfa_verified=True,
    )


def row(
    number: int, doctor: UUID, *, primary: bool = False, ended: bool = False
) -> CareAssignment:
    return CareAssignment(
        assignment_id=UUID(int=500 + number),
        clinic_id=CLINIC,
        patient_id=PATIENT,
        doctor_user_id=doctor,
        is_primary=primary,
        assigned_by=ADMIN,
        assigned_at=datetime(2026, 11, 1, tzinfo=UTC),
        ended_at=NOW if ended else None,
        ended_by=ADMIN if ended else None,
        end_reason=REASON if ended else None,
    )


class World:
    def __init__(self, *rows: CareAssignment) -> None:
        self.teams = FakeCareTeams(*rows)
        self.staff = FakeStaff(DOCTOR, OTHER_DOCTOR, THIRD_DOCTOR)
        self.patients: PatientDirectoryPort = FakeDirectory()
        self.clock = FixedClock(NOW)
        self.ids = FakeIds()
        self.assign = AssignDoctorCommandHandler(
            patients=self.patients,
            staff=self.staff,
            teams=self.teams,
            ids=self.ids,
            clock=self.clock,
        )
        self.primary = SetPrimaryDoctorCommandHandler(teams=self.teams)
        self.reassign = ReassignDoctorCommandHandler(
            staff=self.staff, teams=self.teams, ids=self.ids, clock=self.clock
        )
        self.end = EndAssignmentCommandHandler(teams=self.teams, clock=self.clock)


def assign(doctor: UUID, *, primary: bool = False) -> AssignDoctorCommand:
    return AssignDoctorCommand(
        actor=admin(), patient_id=PATIENT, doctor_user_id=doctor, is_primary=primary
    )


# AssignDoctorCommand.


def test_the_first_assigned_doctor_becomes_the_primary() -> None:
    world = World()

    created = world.assign.handle(assign(DOCTOR))

    assert created.is_primary is True
    assert created.assigned_by == ADMIN
    assert created.assigned_at == NOW
    assert created.clinic_id == CLINIC
    assert world.teams.open_team(PATIENT).open_assignments == (created,)


def test_a_second_doctor_joins_and_a_new_primary_replaces_the_old_in_one_change() -> (
    None
):
    world = World(row(1, DOCTOR, primary=True))

    world.assign.handle(assign(OTHER_DOCTOR, primary=True))

    team = world.teams.open_team(PATIENT).open_assignments
    assert sorted((a.doctor_user_id.int, a.is_primary) for a in team) == [
        (DOCTOR.int, False),
        (OTHER_DOCTOR.int, True),
    ]
    assert len(world.teams.applied) == 1


def test_assigning_requires_the_permission_before_looking_up_anything() -> None:
    world = World()
    command = AssignDoctorCommand(
        actor=admin(PermissionCode.CARE_TEAM_READ),
        patient_id=UUID(int=404),
        doctor_user_id=UUID(int=404),
        is_primary=False,
    )

    with pytest.raises(PermissionDeniedError):
        world.assign.handle(command)


@pytest.mark.parametrize(
    ("patient", "doctor"),
    [(UUID(int=404), DOCTOR), (PATIENT, UUID(int=404))],
    ids=["unknown patient", "doctor of another clinic or inactive"],
)
def test_a_patient_or_doctor_outside_the_clinic_is_not_found(
    patient: UUID, doctor: UUID
) -> None:
    world = World()

    with pytest.raises(ResourceNotFoundError):
        world.assign.handle(
            AssignDoctorCommand(
                actor=admin(),
                patient_id=patient,
                doctor_user_id=doctor,
                is_primary=False,
            )
        )

    assert world.teams.applied == []


def test_assigning_the_same_doctor_twice_conflicts() -> None:
    world = World(row(1, DOCTOR, primary=True))

    with pytest.raises(ConflictError):
        world.assign.handle(assign(DOCTOR))


# SetPrimaryDoctorCommand.


def test_designating_a_primary_swaps_the_role() -> None:
    world = World(row(1, DOCTOR, primary=True), row(2, OTHER_DOCTOR))

    result = world.primary.handle(
        SetPrimaryDoctorCommand(actor=admin(), assignment_id=UUID(int=502))
    )

    assert result.doctor_user_id == OTHER_DOCTOR and result.is_primary
    assert not world.teams.rows[UUID(int=501)].is_primary


def test_an_ended_assignment_cannot_be_designated_and_an_unknown_one_is_404() -> None:
    world = World(row(1, DOCTOR, primary=True), row(2, OTHER_DOCTOR, ended=True))

    with pytest.raises(InvalidStateTransitionError):
        world.primary.handle(
            SetPrimaryDoctorCommand(actor=admin(), assignment_id=UUID(int=502))
        )
    with pytest.raises(ResourceNotFoundError):
        world.primary.handle(
            SetPrimaryDoctorCommand(actor=admin(), assignment_id=UUID(int=999))
        )


# ReassignDoctorCommand.


def test_reassigning_hands_the_role_to_the_new_doctor_and_keeps_the_history() -> None:
    world = World(row(1, DOCTOR, primary=True))

    created = world.reassign.handle(
        ReassignDoctorCommand(
            actor=admin(),
            assignment_id=UUID(int=501),
            new_doctor_user_id=OTHER_DOCTOR,
            reason=REASON,
        )
    )

    old = world.teams.rows[UUID(int=501)]
    assert (created.doctor_user_id, created.is_primary) == (OTHER_DOCTOR, True)
    assert old.ended_at == NOW and old.end_reason == REASON and not old.is_primary


def test_reassigning_needs_a_reason_an_active_open_assignment_and_a_valid_doctor() -> (
    None
):
    world = World(row(1, DOCTOR, primary=True), row(2, OTHER_DOCTOR, ended=True))

    def command(
        assignment: int, doctor: UUID, reason: str = REASON
    ) -> ReassignDoctorCommand:
        return ReassignDoctorCommand(
            actor=admin(),
            assignment_id=UUID(int=assignment),
            new_doctor_user_id=doctor,
            reason=reason,
        )

    with pytest.raises(ReasonRequiredError):
        world.reassign.handle(command(501, THIRD_DOCTOR, "corto"))
    with pytest.raises(InvalidStateTransitionError):
        world.reassign.handle(command(502, THIRD_DOCTOR))
    with pytest.raises(ResourceNotFoundError):
        world.reassign.handle(command(501, UUID(int=404)))
    with pytest.raises(ResourceNotFoundError):
        world.reassign.handle(command(999, THIRD_DOCTOR))
    with pytest.raises(ConflictError):
        World(row(1, DOCTOR, primary=True), row(3, THIRD_DOCTOR)).reassign.handle(
            command(501, THIRD_DOCTOR)
        )


# EndAssignmentCommand.


def end(
    assignment: int, *, successor: int | None = None, reason: str = REASON
) -> EndAssignmentCommand:
    return EndAssignmentCommand(
        actor=admin(),
        assignment_id=UUID(int=assignment),
        reason=reason,
        new_primary_assignment_id=None if successor is None else UUID(int=successor),
    )


def test_withdrawing_a_secondary_doctor_ends_it_with_date_and_reason() -> None:
    world = World(row(1, DOCTOR, primary=True), row(2, OTHER_DOCTOR))

    ended = world.end.handle(end(502))

    assert ended.ended_at == NOW and ended.end_reason == REASON
    assert world.teams.rows[UUID(int=501)].is_primary


def test_withdrawing_the_primary_needs_a_successor() -> None:
    world = World(row(1, DOCTOR, primary=True), row(2, OTHER_DOCTOR))

    with pytest.raises(ConflictError):
        world.end.handle(end(501))
    world.end.handle(end(501, successor=502))

    assert world.teams.rows[UUID(int=502)].is_primary
    assert not world.teams.rows[UUID(int=501)].is_open


def test_the_only_primary_doctor_cannot_be_withdrawn_without_replacement() -> None:
    world = World(row(1, DOCTOR, primary=True))

    with pytest.raises(ConflictError):
        world.end.handle(end(501))

    assert world.teams.applied == []


def test_withdrawing_needs_a_reason_and_an_open_assignment() -> None:
    world = World(row(1, DOCTOR, primary=True), row(2, OTHER_DOCTOR, ended=True))

    with pytest.raises(ReasonRequiredError):
        world.end.handle(end(501, reason="x"))
    with pytest.raises(InvalidStateTransitionError):
        world.end.handle(end(502))


def test_every_decision_requires_the_assign_permission() -> None:
    world = World(row(1, DOCTOR, primary=True), row(2, OTHER_DOCTOR))
    reader = admin(PermissionCode.CARE_TEAM_READ)

    with pytest.raises(PermissionDeniedError):
        world.primary.handle(
            SetPrimaryDoctorCommand(actor=reader, assignment_id=UUID(int=502))
        )
    with pytest.raises(PermissionDeniedError):
        world.reassign.handle(
            ReassignDoctorCommand(
                actor=reader,
                assignment_id=UUID(int=501),
                new_doctor_user_id=THIRD_DOCTOR,
                reason=REASON,
            )
        )
    with pytest.raises(PermissionDeniedError):
        world.end.handle(
            EndAssignmentCommand(
                actor=reader,
                assignment_id=UUID(int=502),
                reason=REASON,
                new_primary_assignment_id=None,
            )
        )

    assert world.teams.applied == []


# Through the bus with the audit decorator.


def test_dispatched_through_the_bus_the_decision_leaves_an_audit_row() -> None:
    world, log = World(), InMemoryAuditLog()
    bus = InMemoryCommandBus(
        [
            bind(
                AssignDoctorCommand,
                AuditingCommandHandler(world.assign, log, world.clock),
            )
        ]
    )

    created = bus.dispatch(assign(DOCTOR))

    [entry] = log.entries
    assert entry.action == "DOCTOR_ASSIGNED"
    assert entry.entity_type == "CARE_TEAM_ASSIGNMENT"
    assert entry.entity_id == created.assignment_id
    assert entry.clinic_id == CLINIC and entry.actor_user_id == ADMIN


def test_a_refused_decision_leaves_no_audit_row() -> None:
    world, log = World(row(1, DOCTOR, primary=True)), InMemoryAuditLog()
    handler = AuditingCommandHandler(world.assign, log, world.clock)

    with pytest.raises(ConflictError):
        handler.handle(assign(DOCTOR))

    assert log.entries == []
