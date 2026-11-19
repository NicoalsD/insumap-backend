"""Ports of the access control and audit of clinical reads (P09 and P11).

Minimal version written by the records branch so it can merge with the access
branch: the names follow ``.agents/design-patterns.md`` (P09, P11). The proxy
(``PatientRecordAccessProxy``) and the audit decorator
(``PhiAccessAuditDecorator``) implement ``PatientRecordPort``; the use cases
only call ``read_record`` to learn whether the actor may read the patient.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from insumap.application.common.actor import Actor


class AccessPurpose(StrEnum):
    CARE = "CARE"
    SELF = "SELF"
    ADMINISTRATION = "ADMINISTRATION"
    AI_PROCESSING = "AI_PROCESSING"


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientRecord:
    patient_id: UUID
    glucose_mg_dl: tuple[Decimal, ...]


class PatientRecordPort(ABC):
    """Who may read a patient. A denied read raises ``NOT_FOUND`` or ``FORBIDDEN``."""

    @abstractmethod
    def read_record(
        self, actor: Actor, patient_id: UUID, purpose: AccessPurpose
    ) -> PatientRecord:
        """Return the record if ``actor`` may read it; raise ``InsumapError`` if not."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DataAccessRecord:
    occurred_at: datetime
    actor_user_id: UUID
    actor_role: str
    clinic_id: UUID | None
    patient_id: UUID
    resource_type: str
    purpose: AccessPurpose
    outcome: str
    request_id: str | None


class DataAccessLogPort(ABC):
    @abstractmethod
    def record_granted(self, record: DataAccessRecord) -> None:
        """Same transaction as the read. If it fails, the read fails."""

    @abstractmethod
    def record_denied(self, record: DataAccessRecord) -> None:
        """Short independent transaction: committed even if the request rolls back."""
