"""Staged patients between the preview and the confirmation, in this process.

No table of ``insumap-database`` holds the validated rows of a preview (the
raw row is never stored and ``import_rows`` has no payload). The staged
patients keep only sealed documents, so they are kept here with a time limit
and dropped after a confirmation. A deployment with several API processes
needs a shared store before the confirmation can run on any of them.

Pattern: P20 Template Method (the store is what the pipeline hands over)
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import final, override
from uuid import UUID

from insumap.application.onboarding.ports import StagedImportStorePort, StagedPatient
from insumap.shared.field_limits import FieldLimits
from insumap.shared.time import Clock


@final
class ProcessStagedImportStore(StagedImportStorePort):
    """Thread-safe map from batch id to its staged patients, with an expiry."""

    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock
        self._max_age = timedelta(minutes=FieldLimits.IMPORT_PREVIEW_MAX_AGE_MINUTES)
        self._lock = threading.Lock()
        self._entries: dict[UUID, tuple[datetime, tuple[StagedPatient, ...]]] = {}

    @override
    def put(self, batch_id: UUID, patients: tuple[StagedPatient, ...]) -> None:
        with self._lock:
            self._entries[batch_id] = (self._clock.now(), patients)

    @override
    def peek(self, batch_id: UUID) -> tuple[StagedPatient, ...] | None:
        with self._lock:
            entry = self._entries.get(batch_id)
            if entry is None:
                return None
            staged_at, patients = entry
            if self._clock.now() - staged_at > self._max_age:
                del self._entries[batch_id]
                return None
            return patients

    @override
    def discard(self, batch_id: UUID) -> None:
        with self._lock:
            self._entries.pop(batch_id, None)
