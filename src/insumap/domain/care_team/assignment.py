"""Care team of a patient: assignments of doctors with history (RF-27 to RF-29).

A patient with an open team has exactly one primary doctor. The aggregate takes
the clock and the identifiers as arguments and returns the rows that change;
the use case persists them in one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from insumap.domain.common.errors import ConflictError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import InvalidStateTransitionError

MACHINE_NAME: Final = "care_team_assignment"
OPEN: Final = "OPEN"
ENDED: Final = "ENDED"

SOLE_PRIMARY_WITHOUT_REPLACEMENT: Final = "primary_without_replacement"
DOCTOR_ALREADY_ASSIGNED: Final = "doctor_already_assigned"


@dataclass(frozen=True, slots=True, kw_only=True)
class CareAssignment:
    """One doctor assigned to one patient, open or ended."""

    assignment_id: UUID
    clinic_id: UUID
    patient_id: UUID
    doctor_user_id: UUID
    is_primary: bool
    assigned_by: UUID
    assigned_at: datetime
    ended_at: datetime | None = None
    ended_by: UUID | None = None
    end_reason: str | None = None

    def is_active(self, at: datetime) -> bool:
        """``True`` while the assignment gives access: open or ending in the future."""
        return self.ended_at is None or self.ended_at > at

    @property
    def is_open(self) -> bool:
        """``True`` if no end was recorded."""
        return self.ended_at is None

    def ended(self, *, by: UUID, at: datetime, reason: Reason) -> CareAssignment:
        """This assignment closed at ``at``; a closed one is never primary."""
        return replace(
            self,
            is_primary=False,
            ended_at=at,
            ended_by=by,
            end_reason=reason.text,
        )

    def with_primary(self, *, primary: bool) -> CareAssignment:
        """This assignment as primary or not."""
        return replace(self, is_primary=primary)


@dataclass(frozen=True, slots=True, kw_only=True)
class CareTeamChange:
    """What an operation changed: rows to update, then rows to insert.

    The order matters: ``updated`` is written first and in order, so a primary
    is demoted or ended before another one is promoted or inserted (the table
    allows one open primary per patient at every statement).
    """

    updated: tuple[CareAssignment, ...] = ()
    added: tuple[CareAssignment, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CareTeam:
    """The open assignments of one patient, as of the moment they were read."""

    patient_id: UUID
    open_assignments: tuple[CareAssignment, ...]

    def assign(
        self,
        *,
        assignment_id: UUID,
        clinic_id: UUID,
        doctor_user_id: UUID,
        is_primary: bool,
        assigned_by: UUID,
        at: datetime,
    ) -> CareTeamChange:
        """Add a doctor: the first is the primary and a new primary replaces the old."""
        if self._find_doctor(doctor_user_id) is not None:
            raise ConflictError(DOCTOR_ALREADY_ASSIGNED)
        primary = is_primary or not self.open_assignments
        demoted = self._demote_primary() if primary else ()
        created = CareAssignment(
            assignment_id=assignment_id,
            clinic_id=clinic_id,
            patient_id=self.patient_id,
            doctor_user_id=doctor_user_id,
            is_primary=primary,
            assigned_by=assigned_by,
            assigned_at=at,
        )
        return CareTeamChange(updated=demoted, added=(created,))

    def make_primary(self, assignment_id: UUID) -> CareTeamChange:
        """Designate a doctor as primary; the previous primary stops being it."""
        target = self._open(assignment_id)
        if target.is_primary:
            return CareTeamChange(updated=(target,))
        return CareTeamChange(
            updated=(*self._demote_primary(), target.with_primary(primary=True))
        )

    def reassign(
        self,
        *,
        assignment_id: UUID,
        new_assignment_id: UUID,
        new_doctor_user_id: UUID,
        by: UUID,
        at: datetime,
        reason: Reason,
    ) -> CareTeamChange:
        """End an assignment and open one for another doctor, who inherits the role."""
        current = self._open(assignment_id)
        if self._find_doctor(new_doctor_user_id) is not None:
            raise ConflictError(DOCTOR_ALREADY_ASSIGNED)
        replacement = CareAssignment(
            assignment_id=new_assignment_id,
            clinic_id=current.clinic_id,
            patient_id=self.patient_id,
            doctor_user_id=new_doctor_user_id,
            is_primary=current.is_primary,
            assigned_by=by,
            assigned_at=at,
        )
        return CareTeamChange(
            updated=(current.ended(by=by, at=at, reason=reason),), added=(replacement,)
        )

    def end(
        self,
        *,
        assignment_id: UUID,
        by: UUID,
        at: datetime,
        reason: Reason,
        new_primary_assignment_id: UUID | None,
    ) -> CareTeamChange:
        """Withdraw a doctor. A primary needs another open doctor to take the role."""
        current = self._open(assignment_id)
        ended = current.ended(by=by, at=at, reason=reason)
        if not current.is_primary:
            return CareTeamChange(updated=(ended,))
        successor = (
            None
            if new_primary_assignment_id is None
            or new_primary_assignment_id == assignment_id
            else self._find(new_primary_assignment_id)
        )
        if successor is None:
            raise ConflictError(SOLE_PRIMARY_WITHOUT_REPLACEMENT)
        return CareTeamChange(updated=(ended, successor.with_primary(primary=True)))

    def _find(self, assignment_id: UUID) -> CareAssignment | None:
        return next(
            (a for a in self.open_assignments if a.assignment_id == assignment_id), None
        )

    def _find_doctor(self, doctor_user_id: UUID) -> CareAssignment | None:
        return next(
            (a for a in self.open_assignments if a.doctor_user_id == doctor_user_id),
            None,
        )

    def _open(self, assignment_id: UUID) -> CareAssignment:
        found = self._find(assignment_id)
        if found is None:
            raise InvalidStateTransitionError(MACHINE_NAME, ENDED, "change")
        return found

    def _demote_primary(self) -> tuple[CareAssignment, ...]:
        return tuple(
            a.with_primary(primary=False) for a in self.open_assignments if a.is_primary
        )
