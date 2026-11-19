"""Ports of the care team use cases."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.care_team.assignment import CareAssignment, CareTeam, CareTeamChange


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignmentFilter:
    """Filters of ``GET /care-team/assignments`` (all optional)."""

    patient_id: UUID | None = None
    doctor_id: UUID | None = None
    ended: bool | None = None


class CareTeamRepositoryPort(ABC):
    """Assignments of doctors to patients, under row level security."""

    @abstractmethod
    def get_assignment(self, assignment_id: UUID) -> CareAssignment | None:
        """One assignment, open or ended, or ``None`` if the session cannot see it."""

    @abstractmethod
    def open_team(self, patient_id: UUID) -> CareTeam:
        """The open assignments of a patient."""

    @abstractmethod
    def apply(self, change: CareTeamChange) -> None:
        """Write the updates in order, then the inserts."""

    @abstractmethod
    def list_assignments(
        self, filters: AssignmentFilter, page: PageRequest
    ) -> Page[CareAssignment]:
        """A page of assignments, oldest first."""

    @abstractmethod
    def count_open_for_doctor(self, doctor_user_id: UUID) -> int:
        """How many open assignments a doctor holds."""


class StaffLookupPort(ABC):
    """Checks the doctors a clinic administrator may assign."""

    @abstractmethod
    def is_active_doctor(self, user_id: UUID) -> bool:
        """``True`` if the user is an active ``DOCTOR`` of the session clinic."""
