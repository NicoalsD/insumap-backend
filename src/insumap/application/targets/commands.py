"""Decisions about the goals: profiles, their versions and the patient assignment (P13).

The clinic administrator writes the catalog; the doctor assigns a profile to a
patient he cares for (``AssignedPatientGate``, P11). Each command runs inside
its transaction and leaves its audit row (P09), both set up by ``CommandGuard``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.application.targets.ports import (
    PatientTargetAssignmentPort,
    TargetProfileCatalogPort,
)
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.target_profile_version import (
    ACTIVE,
    RETIRED,
    PatientTargetAssignment,
    TargetProfileValues,
    TargetProfileVersion,
)
from insumap.shared.time import Clock

PROFILE_ENTITY: Final = "TARGET_PROFILE"
ASSIGNMENT_ENTITY: Final = "PATIENT_TARGET_ASSIGNMENT"
PROFILE_MACHINE: Final = "target_profile"
CODE_TAKEN: Final = "target_profile_code_taken"
VERSION_RACE: Final = "target_profile_version_conflict"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateTargetProfileCommand(Command[TargetProfileVersion]):
    """The clinic administrator creates a profile of its own; version 1 is active."""

    audit_action: ClassVar[str] = "TARGET_PROFILE_CREATED"
    audit_entity_type: ClassVar[str] = PROFILE_ENTITY

    code: str
    values: TargetProfileValues

    @override
    def audit_subject(self, result: TargetProfileVersion) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.id,
            changed_fields=("code", *(f.name for f in fields(self.values))),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateTargetProfileVersionCommand(Command[TargetProfileVersion]):
    """A new version of a clinic profile: the changes applied to the active one."""

    audit_action: ClassVar[str] = "TARGET_PROFILE_VERSIONED"
    audit_entity_type: ClassVar[str] = PROFILE_ENTITY

    profile_id: UUID
    changes: Mapping[str, Any]
    change_reason: str

    @override
    def audit_subject(self, result: TargetProfileVersion) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.id,
            reason=Reason.parse(self.change_reason).text,
            changed_fields=tuple(sorted(self.changes)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignedTargetProfile:
    """The assignment that now holds, with the profile version it points to."""

    assignment: PatientTargetAssignment
    profile: TargetProfileVersion


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignTargetProfileCommand(Command[AssignedTargetProfile]):
    """The doctor assigns a profile to a patient he cares for."""

    audit_action: ClassVar[str] = "TARGET_PROFILE_ASSIGNED"
    audit_entity_type: ClassVar[str] = ASSIGNMENT_ENTITY

    patient_id: UUID
    target_profile_id: UUID

    @override
    def audit_subject(self, result: AssignedTargetProfile) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.assignment.id,
            changed_fields=("target_profile_id",),
        )


@final
class CreateTargetProfileCommandHandler(
    CommandHandler[CreateTargetProfileCommand, TargetProfileVersion]
):
    """Validates the values as a whole and refuses a code the clinic already uses."""

    def __init__(
        self, *, catalog: TargetProfileCatalogPort, ids: IdGenerator, clock: Clock
    ) -> None:
        self._catalog = catalog
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateTargetProfileCommand) -> TargetProfileVersion:
        actor = command.actor
        actor.require(PermissionCode.TARGET_PROFILES_MANAGE)
        if actor.clinic_id is None:
            raise PermissionDeniedError
        command.values.ensure_valid()
        if self._catalog.code_exists(actor.clinic_id, command.code):
            raise ConflictError(CODE_TAKEN)
        at = self._clock.now()
        version = TargetProfileVersion(
            id=self._ids.new_id(),
            clinic_id=actor.clinic_id,
            code=command.code,
            version=1,
            status=ACTIVE,
            values=command.values,
            created_at=at,
            created_by=actor.user_id,
            activated_at=at,
        )
        self._catalog.insert(version)
        return version


@final
class CreateTargetProfileVersionCommandHandler(
    CommandHandler[CreateTargetProfileVersionCommand, TargetProfileVersion]
):
    """Retires the active version and inserts the copy with the next number.

    The retire is written first: ``ux_target_profiles_active`` admits one active
    version per code. A seed (no clinic) is not versioned by a clinic: it answers
    ``404`` like a profile of another clinic.
    """

    def __init__(
        self, *, catalog: TargetProfileCatalogPort, ids: IdGenerator, clock: Clock
    ) -> None:
        self._catalog = catalog
        self._ids = ids
        self._clock = clock

    @override
    def handle(
        self, command: CreateTargetProfileVersionCommand
    ) -> TargetProfileVersion:
        actor = command.actor
        actor.require(PermissionCode.TARGET_PROFILES_MANAGE)
        if actor.clinic_id is None:
            raise PermissionDeniedError
        profile = self._catalog.get(command.profile_id)
        if profile is None or profile.clinic_id != actor.clinic_id:
            raise ResourceNotFoundError
        current = self._catalog.active_of_clinic(actor.clinic_id, profile.code)
        if current is None:
            raise InvalidStateTransitionError(PROFILE_MACHINE, RETIRED, "version")
        reason = Reason.parse(command.change_reason)
        copy = current.copy_for_new_version(
            new_id=self._ids.new_id(),
            changes=command.changes,
            by=actor.user_id,
            change_reason=reason.text,
            at=self._clock.now(),
        )
        if not self._catalog.retire(current.id):
            raise ConflictError(VERSION_RACE)
        self._catalog.insert(copy)
        return copy


@final
class AssignTargetProfileCommandHandler(
    CommandHandler[AssignTargetProfileCommand, AssignedTargetProfile]
):
    """Ends the open assignment and opens one for the profile (other clinic: 404)."""

    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        catalog: TargetProfileCatalogPort,
        assignments: PatientTargetAssignmentPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._catalog = catalog
        self._assignments = assignments
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: AssignTargetProfileCommand) -> AssignedTargetProfile:
        actor = command.actor
        patient_id = self._gate.enter(
            actor,
            PermissionCode.TARGET_PROFILES_ASSIGN,
            command.patient_id,
            DataResource.TREATMENT_PLAN,
        )
        if actor.clinic_id is None:
            raise PermissionDeniedError
        profile = self._catalog.get(command.target_profile_id)
        if profile is None or profile.clinic_id not in (None, actor.clinic_id):
            raise ResourceNotFoundError
        if not profile.is_active:
            raise InvalidStateTransitionError(PROFILE_MACHINE, profile.status, "assign")
        open_assignment = self._assignments.open_for_patient(patient_id)
        if open_assignment is not None and (
            open_assignment.target_profile_id == profile.id
        ):
            return AssignedTargetProfile(assignment=open_assignment, profile=profile)
        at = self._clock.now()
        if open_assignment is not None:
            self._assignments.end(open_assignment.ended(at))
        assignment = PatientTargetAssignment(
            id=self._ids.new_id(),
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            target_profile_id=profile.id,
            assigned_by=actor.user_id,
            assigned_at=at,
        )
        self._assignments.insert(assignment)
        return AssignedTargetProfile(assignment=assignment, profile=profile)
