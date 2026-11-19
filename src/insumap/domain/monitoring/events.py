"""Domain events of the patient records (P17 Observer).

They carry identifiers only, never glucose values or notes: a subscriber reads
the row it needs under its own transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from insumap.domain.common.events import DomainEvent


class HypoglycemiaLevel(StrEnum):
    """Level 1 is below the range; level 2 is below the very low threshold."""

    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"


@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseReadingRecorded(DomainEvent):
    """A glucose reading was saved (committed)."""

    reading_id: UUID
    patient_id: UUID
    clinic_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class HypoglycemiaDetected(DomainEvent):
    """A saved reading is under the low limit of the patient's target profile."""

    reading_id: UUID
    patient_id: UUID
    clinic_id: UUID
    level: HypoglycemiaLevel
