"""Ports of the triage dashboard, the reviews and the clinical notes.

Infrastructure implements them over PostgreSQL under the row level security of
each transaction. Only what this module needs: the rest comes from the ports of
the patient records, the metrics and the alerts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.clinical_notes.note import ClinicalNote
from insumap.domain.dashboard.triage import TriageReview


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignedPatientRow:
    """A patient with an open assignment to the doctor (name for the list)."""

    patient_id: UUID
    full_name: str


class TriageRosterPort(ABC):
    """The patients a doctor is assigned to, through the care team table."""

    @abstractmethod
    def assigned_patients(self, doctor_id: UUID) -> Sequence[AssignedPatientRow]:
        """Every open assignment of the doctor, one row per patient."""


class OpenAlertCountPort(ABC):
    """Alerts a patient still has open: ``OPEN`` or ``ESCALATED``."""

    @abstractmethod
    def open_counts(self, patient_ids: Collection[UUID]) -> Mapping[UUID, int]:
        """The open alerts per patient; a patient without any is absent."""


class TriageReviewPort(ABC):
    """``care.triage_reviews``: append only, the latest row of a doctor wins."""

    @abstractmethod
    def latest_reviews(
        self, doctor_id: UUID, patient_ids: Collection[UUID]
    ) -> Mapping[UUID, datetime]:
        """The last moment the doctor reviewed each patient."""

    @abstractmethod
    def add(self, review: TriageReview) -> None:
        """Insert the review row."""


class ClinicalNotePort(ABC):
    """``care.clinical_notes``: append only, read by the assigned team."""

    @abstractmethod
    def add(self, note: ClinicalNote) -> None:
        """Insert the note row."""

    @abstractmethod
    def find(self, patient_id: UUID, note_id: UUID) -> ClinicalNote | None:
        """A note of the patient, or ``None`` (another patient's note is not found)."""

    @abstractmethod
    def list(self, patient_id: UUID, page: PageRequest) -> Page[ClinicalNote]:
        """The notes of a patient, oldest first."""
