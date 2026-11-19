"""Domain events of the patient import (P17)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from insumap.domain.common.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientsImported(DomainEvent):
    """A confirmation created patients; carries counts and identifiers only."""

    batch_id: UUID
    clinic_id: UUID
    created: int
