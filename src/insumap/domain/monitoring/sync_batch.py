"""A batch of records sent together: offline queue, CGM file or simulator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SyncSource(StrEnum):
    OFFLINE_QUEUE = "OFFLINE_QUEUE"
    CGM_CSV = "CGM_CSV"
    SIMULATOR = "SIMULATOR"


@dataclass(frozen=True, slots=True, kw_only=True)
class SyncBatch:
    """Written once with the final counts, in the transaction of its records."""

    id: UUID
    clinic_id: UUID
    patient_id: UUID
    source: SyncSource
    submitted_by: UUID
    total_items: int
    created_count: int
    duplicate_count: int
    rejected_count: int
    received_at: datetime
    file_sha256: str | None = None
