"""The doctor's answer to a pattern finding: a dismissal that is never edited (RF-68).

A finding of IA3 is append-only, so the answer is a row of its own
(``ai.pattern_finding_reviews``). A finding is dismissed once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits


@final
class FindingNoteInvalidError(InsumapError):
    """The note that dismisses a finding is empty, or longer than the column allows."""

    def __init__(self) -> None:
        super().__init__(ErrorCode.VALIDATION_ERROR)


def parse_dismissal_note(raw: str) -> str:
    """Trim ``raw`` and check its length against ``FieldLimits``."""
    text = raw.strip()
    if not (
        FieldLimits.PATTERN_FINDING_NOTE_MIN_LENGTH
        <= len(text)
        <= FieldLimits.PATTERN_FINDING_NOTE_MAX_LENGTH
    ):
        raise FindingNoteInvalidError
    return text


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class FindingDismissal:
    """One row of ``ai.pattern_finding_reviews``: the doctor dismisses a finding."""

    dismissal_id: UUID
    clinic_id: UUID
    patient_id: UUID
    finding_id: UUID
    note: str
    reviewed_by: UUID
    reviewed_at: datetime
