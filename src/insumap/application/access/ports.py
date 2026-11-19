"""Ports of the access to clinical data and of its audit (P09, P11)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.domain.access.policy import PatientRef
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.identity.roles import Role


class AccessPurpose(StrEnum):
    """Why the data is read (``audit.data_access_log.purpose``)."""

    CARE = "CARE"
    SELF = "SELF"
    ADMINISTRATION = "ADMINISTRATION"
    AI_PROCESSING = "AI_PROCESSING"


class DataResource(StrEnum):
    """What is read (``audit.data_access_log.resource_type``)."""

    GLUCOSE_READINGS = "GLUCOSE_READINGS"
    INSULIN_DOSES = "INSULIN_DOSES"
    MEALS = "MEALS"
    PHYSICAL_ACTIVITIES = "PHYSICAL_ACTIVITIES"
    SYMPTOMS = "SYMPTOMS"
    LAB_RESULTS = "LAB_RESULTS"
    GLYCEMIC_METRICS = "GLYCEMIC_METRICS"
    TREATMENT_PLAN = "TREATMENT_PLAN"
    CLINICAL_NOTES = "CLINICAL_NOTES"
    ALERTS = "ALERTS"
    AI_OUTPUTS = "AI_OUTPUTS"
    MESSAGES = "MESSAGES"
    PATIENT_TIMELINE = "PATIENT_TIMELINE"
    REPORT = "REPORT"
    TRIAGE_LIST = "TRIAGE_LIST"
    PATIENT_DEMOGRAPHICS = "PATIENT_DEMOGRAPHICS"
    PATIENT_LIST = "PATIENT_LIST"
    PATIENT_DOCUMENT = "PATIENT_DOCUMENT"


class DataAccessOutcome(StrEnum):
    """Whether the read was allowed (``audit.data_access_log.outcome``)."""

    GRANTED = "GRANTED"
    DENIED = "DENIED"


class DataAccessAction(StrEnum):
    """What was done with the data (``audit.data_access_log.action``).

    A report or an export is an ``EXPORT`` even when it only reads.
    """

    READ = "READ"
    EXPORT = "EXPORT"
    DECRYPT = "DECRYPT"


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientRecord:
    """The handle of a patient record a caller was allowed to read.

    Modules that read clinical data return a richer record built on this one;
    the guarantee is the same: it exists only after the proxy said yes.
    """

    patient_id: UUID
    clinic_id: UUID


class PatientRecordPort(ABC):
    """Read access to the clinical record of a patient.

    The container hands out only the audited proxy chain, so no use case can
    read a record without the care team check and the audit row.
    """

    @abstractmethod
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
        action: DataAccessAction = DataAccessAction.READ,
    ) -> PatientRecord:
        """Return the record, or raise a ``NOT_FOUND`` or ``FORBIDDEN`` error."""


class PatientDirectoryPort(ABC):
    """Finds a patient under row level security."""

    @abstractmethod
    def find(self, patient_id: UUID) -> PatientRef | None:
        """The patient, or ``None`` if it does not exist or is of another clinic."""


class CareTeamAssignmentPort(ABC):
    """Reads the assignments the proxy checks."""

    @abstractmethod
    def for_patient(self, patient_id: UUID) -> Sequence[CareAssignment]:
        """The assignments of the patient that the session may see."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DataAccessRecord:
    """One row of ``audit.data_access_log``: who read what, never the data."""

    occurred_at: datetime
    clinic_id: UUID | None
    actor_user_id: UUID
    actor_role: Role
    patient_id: UUID | None
    resource: DataResource
    purpose: AccessPurpose
    outcome: DataAccessOutcome
    request_id: str | None
    action: DataAccessAction = DataAccessAction.READ


class DataAccessLogPort(ABC):
    """Appends the rows of ``audit.data_access_log``."""

    @abstractmethod
    def record_granted(self, record: DataAccessRecord) -> None:
        """Same transaction as the read: if the write fails, the read fails."""

    @abstractmethod
    def record_denied(self, record: DataAccessRecord) -> None:
        """Short independent transaction: it stays even if the request rolls back."""

    def record_granted_many(self, records: Sequence[DataAccessRecord]) -> None:
        """Granted rows of one list in the same transaction (a loop by default)."""
        for record in records:
            self.record_granted(record)
