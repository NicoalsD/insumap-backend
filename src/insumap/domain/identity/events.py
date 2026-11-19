"""Domain events of the identity module."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from insumap.domain.common.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientActivated(DomainEvent):
    """A patient activated the account and accepted the privacy notice."""

    user_id: UUID
    patient_id: UUID
    clinic_id: UUID
