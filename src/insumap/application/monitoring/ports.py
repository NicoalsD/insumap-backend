"""Ports of the patient records. Infrastructure implements them over PostgreSQL."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from insumap.application.monitoring.paging import PageQuery
from insumap.domain.monitoring.clinical_event import ClinicalEvent
from insumap.domain.monitoring.glucose import GlucoseReading, ReadingSource
from insumap.domain.monitoring.record import ClinicalRecord
from insumap.domain.monitoring.records import SymptomEntry
from insumap.domain.monitoring.sync_batch import SyncBatch
from insumap.domain.monitoring.timeline import TimelineEventType
from insumap.domain.monitoring.validation import PreviousReading, ValidationParams


class ClinicalRecordKind(StrEnum):
    """The tables other than glucose that share the same port."""

    INSULIN_DOSES = "insulin-doses"
    MEALS = "meals"
    ACTIVITIES = "activities"
    SYMPTOMS = "symptoms"
    LAB_RESULTS = "lab-results"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadingFilters:
    """Optional filters of the reading listing; ``status`` may be ``CORRECTED``."""

    source: ReadingSource | None = None
    status: str | None = None


class GlucoseReadingPort(ABC):
    """``monitoring.glucose_readings`` and its ``reading_issues``."""

    @abstractmethod
    def add(self, reading: GlucoseReading) -> None:
        """Insert the reading and one issue row per flag."""

    @abstractmethod
    def find_by_client_id(
        self, patient_id: UUID, client_reading_id: UUID
    ) -> GlucoseReading | None:
        """The reading the patient already sent with that client id."""

    @abstractmethod
    def get(self, patient_id: UUID, reading_id: UUID) -> GlucoseReading | None:
        """A reading with its lifecycle (is it corrected or annulled already?)."""

    @abstractmethod
    def previous_before(
        self, patient_id: UUID, at: datetime, *, excluding: UUID | None = None
    ) -> PreviousReading | None:
        """The current reading right before ``at``, the history of the checks.

        ``excluding`` leaves out the row a correction is about to supersede.
        """

    @abstractmethod
    def list(
        self, patient_id: UUID, query: PageQuery, filters: ReadingFilters
    ) -> Sequence[GlucoseReading]:
        """Readings newest first, at most ``query.limit``."""


class ClinicalRecordPort(ABC):
    """Insulin doses, meals, activities, symptoms and lab results."""

    @abstractmethod
    def add(self, record: ClinicalRecord) -> None:
        """Insert the row (append only)."""

    @abstractmethod
    def find_by_client_id(
        self, kind: ClinicalRecordKind, patient_id: UUID, client_record_id: UUID
    ) -> ClinicalRecord | None:
        """The record the patient already sent with that client id."""

    @abstractmethod
    def get(
        self, kind: ClinicalRecordKind, patient_id: UUID, record_id: UUID
    ) -> ClinicalRecord | None:
        """A record with its lifecycle."""

    @abstractmethod
    def list(
        self, kind: ClinicalRecordKind, patient_id: UUID, query: PageQuery
    ) -> Sequence[ClinicalRecord]:
        """Records newest first, at most ``query.limit``."""


class TimelinePort(ABC):
    """The five timeline tables read together."""

    @abstractmethod
    def events(
        self,
        patient_id: UUID,
        query: PageQuery,
        types: frozenset[TimelineEventType],
    ) -> Sequence[ClinicalEvent]:
        """Events newest first of the requested types, at most ``query.limit``."""

    @abstractmethod
    def effective_events(
        self, patient_id: UUID, query: PageQuery
    ) -> Sequence[ClinicalEvent]:
        """Current rows (not superseded, not annulled) for an export."""


class ValidationSettingsPort(ABC):
    """``care.reading_validation_settings``: the thresholds of the chain."""

    @abstractmethod
    def active_for(self, clinic_id: UUID) -> ValidationParams:
        """The active version of the clinic, or the global seed."""


class SyncBatchPort(ABC):
    @abstractmethod
    def add(self, batch: SyncBatch) -> None:
        """Insert the batch with its final counts."""


class SymptomCatalogPort(ABC):
    @abstractmethod
    def find_active(self, clinic_id: UUID, code: str) -> SymptomEntry | None:
        """The active catalog entry of the clinic (or global) with that code."""


class ActivePlanPort(ABC):
    @abstractmethod
    def active_plan_id(self, patient_id: UUID) -> UUID | None:
        """The active treatment plan of the patient, if any."""
