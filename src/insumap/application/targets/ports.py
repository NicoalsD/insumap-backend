"""Ports of the target profile catalog and of the assignment to patients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.metrics.target_profile_version import (
    PatientTargetAssignment,
    TargetProfileVersion,
)


class TargetProfileCatalogPort(ABC):
    """``care.target_profiles`` under row level security (seeds and the clinic's)."""

    @abstractmethod
    def list_active(
        self, population: str | None, page: PageRequest
    ) -> Page[TargetProfileVersion]:
        """Active versions the session may see, by id."""

    @abstractmethod
    def get(self, profile_id: UUID) -> TargetProfileVersion | None:
        """One version, or ``None`` if it does not exist or is not visible."""

    @abstractmethod
    def versions_of(
        self, clinic_id: UUID | None, code: str
    ) -> tuple[TargetProfileVersion, ...]:
        """Every version of a code of a clinic (or of the seeds), oldest first."""

    @abstractmethod
    def active_of_clinic(
        self, clinic_id: UUID, code: str
    ) -> TargetProfileVersion | None:
        """The active version a clinic owns for a code."""

    @abstractmethod
    def code_exists(self, clinic_id: UUID, code: str) -> bool:
        """``True`` if the clinic already has a profile with this code."""

    @abstractmethod
    def retire(self, profile_id: UUID) -> bool:
        """Move an active version to ``RETIRED``; ``False`` if no row changed."""

    @abstractmethod
    def insert(self, version: TargetProfileVersion) -> None:
        """Insert a new version (the active one must be retired first)."""


class PatientTargetAssignmentPort(ABC):
    """``care.patient_target_assignments``: one open assignment per patient."""

    @abstractmethod
    def open_for_patient(self, patient_id: UUID) -> PatientTargetAssignment | None:
        """The open assignment of a patient, if any."""

    @abstractmethod
    def end(self, assignment: PatientTargetAssignment) -> None:
        """Write the end of an open assignment (before a new one is inserted)."""

    @abstractmethod
    def insert(self, assignment: PatientTargetAssignment) -> None:
        """Insert the new open assignment."""
