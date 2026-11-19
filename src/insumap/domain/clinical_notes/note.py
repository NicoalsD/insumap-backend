"""Clinical notes: each one is append only and may correct an earlier one."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicalNote:
    """One note of a doctor about a patient; a wrong note is fixed by a new one.

    ``supersedes_id`` names the note this one corrects (``body`` in the database,
    ``text`` in the API). Rows are never updated or deleted.
    """

    id: UUID
    clinic_id: UUID
    patient_id: UUID
    author_user_id: UUID
    body: str
    supersedes_id: UUID | None
    created_at: datetime
