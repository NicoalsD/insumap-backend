"""Decisions about the care team: assign, designate, reassign and withdraw (P13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.access.ports import PatientDirectoryPort
from insumap.application.care_team.ports import CareTeamRepositoryPort, StaffLookupPort
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.domain.care_team.assignment import (
    ENDED,
    MACHINE_NAME,
    CareAssignment,
    CareTeam,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

ASSIGNMENT_ENTITY = "CARE_TEAM_ASSIGNMENT"


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignDoctorCommand(Command[CareAssignment]):
    """The clinic administrator adds a doctor to the care team of a patient."""

    audit_action: ClassVar[str] = "DOCTOR_ASSIGNED"
    audit_entity_type: ClassVar[str] = ASSIGNMENT_ENTITY

    patient_id: UUID
    doctor_user_id: UUID
    is_primary: bool

    @override
    def audit_subject(self, result: CareAssignment) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.assignment_id,
            changed_fields=("doctor_user_id", "is_primary"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SetPrimaryDoctorCommand(Command[CareAssignment]):
    """The clinic administrator designates the primary doctor of a patient."""

    audit_action: ClassVar[str] = "PRIMARY_DOCTOR_CHANGED"
    audit_entity_type: ClassVar[str] = ASSIGNMENT_ENTITY

    assignment_id: UUID

    @override
    def audit_subject(self, result: CareAssignment) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.assignment_id,
            changed_fields=("is_primary",),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReassignDoctorCommand(Command[CareAssignment]):
    """The clinic administrator hands an assignment over to another doctor."""

    audit_action: ClassVar[str] = "DOCTOR_REASSIGNED"
    audit_entity_type: ClassVar[str] = ASSIGNMENT_ENTITY

    assignment_id: UUID
    new_doctor_user_id: UUID
    reason: str

    @override
    def audit_subject(self, result: CareAssignment) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.assignment_id,
            reason=Reason.parse(self.reason).text,
            changed_fields=("doctor_user_id", "ended_at", "end_reason"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EndAssignmentCommand(Command[CareAssignment]):
    """The clinic administrator withdraws a doctor from a patient."""

    audit_action: ClassVar[str] = "DOCTOR_WITHDRAWN"
    audit_entity_type: ClassVar[str] = ASSIGNMENT_ENTITY

    assignment_id: UUID
    reason: str
    new_primary_assignment_id: UUID | None

    @override
    def audit_subject(self, result: CareAssignment) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.assignment_id,
            reason=Reason.parse(self.reason).text,
            changed_fields=("ended_at", "end_reason", "is_primary"),
        )


@final
class AssignDoctorCommandHandler(CommandHandler[AssignDoctorCommand, CareAssignment]):
    """Adds a doctor of the clinic to the team; the first one becomes the primary."""

    def __init__(
        self,
        *,
        patients: PatientDirectoryPort,
        staff: StaffLookupPort,
        teams: CareTeamRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._patients = patients
        self._staff = staff
        self._teams = teams
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: AssignDoctorCommand) -> CareAssignment:
        actor = command.actor
        actor.require(PermissionCode.CARE_TEAM_ASSIGN)
        patient = self._patients.find(command.patient_id)
        if (
            patient is None
            or actor.clinic_id is None
            or not self._staff.is_active_doctor(command.doctor_user_id)
        ):
            raise ResourceNotFoundError
        change = self._teams.open_team(patient.patient_id).assign(
            assignment_id=self._ids.new_id(),
            clinic_id=actor.clinic_id,
            doctor_user_id=command.doctor_user_id,
            is_primary=command.is_primary,
            assigned_by=actor.user_id,
            at=self._clock.now(),
        )
        self._teams.apply(change)
        return change.added[0]


class _OpenAssignmentLoader:
    """Finds the open assignment and the team it belongs to."""

    def __init__(self, teams: CareTeamRepositoryPort) -> None:
        self._teams = teams

    def load(self, assignment_id: UUID) -> tuple[CareAssignment, CareTeam]:
        """The assignment and the open team of its patient (404 or 409)."""
        assignment = self._teams.get_assignment(assignment_id)
        if assignment is None:
            raise ResourceNotFoundError
        if not assignment.is_open:
            raise InvalidStateTransitionError(MACHINE_NAME, ENDED, "change")
        return assignment, self._teams.open_team(assignment.patient_id)


@final
class SetPrimaryDoctorCommandHandler(
    CommandHandler[SetPrimaryDoctorCommand, CareAssignment]
):
    """Makes an assignment primary; the previous primary stops being it."""

    def __init__(self, *, teams: CareTeamRepositoryPort) -> None:
        self._teams = teams
        self._open = _OpenAssignmentLoader(teams)

    @override
    def handle(self, command: SetPrimaryDoctorCommand) -> CareAssignment:
        command.actor.require(PermissionCode.CARE_TEAM_ASSIGN)
        assignment, team = self._open.load(command.assignment_id)
        change = team.make_primary(assignment.assignment_id)
        self._teams.apply(change)
        return next(
            row
            for row in change.updated
            if row.assignment_id == assignment.assignment_id
        )


@final
class ReassignDoctorCommandHandler(
    CommandHandler[ReassignDoctorCommand, CareAssignment]
):
    """Ends the assignment and opens one for the new doctor with the same role."""

    def __init__(
        self,
        *,
        staff: StaffLookupPort,
        teams: CareTeamRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._staff = staff
        self._teams = teams
        self._open = _OpenAssignmentLoader(teams)
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: ReassignDoctorCommand) -> CareAssignment:
        command.actor.require(PermissionCode.CARE_TEAM_ASSIGN)
        reason = Reason.parse(command.reason)
        assignment, team = self._open.load(command.assignment_id)
        if not self._staff.is_active_doctor(command.new_doctor_user_id):
            raise ResourceNotFoundError
        change = team.reassign(
            assignment_id=assignment.assignment_id,
            new_assignment_id=self._ids.new_id(),
            new_doctor_user_id=command.new_doctor_user_id,
            by=command.actor.user_id,
            at=self._clock.now(),
            reason=reason,
        )
        self._teams.apply(change)
        return change.added[0]


@final
class EndAssignmentCommandHandler(CommandHandler[EndAssignmentCommand, CareAssignment]):
    """Withdraws a doctor; the access to the patient ends with the assignment."""

    def __init__(self, *, teams: CareTeamRepositoryPort, clock: Clock) -> None:
        self._teams = teams
        self._open = _OpenAssignmentLoader(teams)
        self._clock = clock

    @override
    def handle(self, command: EndAssignmentCommand) -> CareAssignment:
        command.actor.require(PermissionCode.CARE_TEAM_ASSIGN)
        reason = Reason.parse(command.reason)
        assignment, team = self._open.load(command.assignment_id)
        change = team.end(
            assignment_id=assignment.assignment_id,
            by=command.actor.user_id,
            at=self._clock.now(),
            reason=reason,
            new_primary_assignment_id=command.new_primary_assignment_id,
        )
        self._teams.apply(change)
        return change.updated[0]
