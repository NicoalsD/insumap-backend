"""Follow-up controls of a patient: the doctor schedules them and closes them (RF-86).

A control is ``SCHEDULED`` until it is closed as ``DONE`` or ``MISSED`` with a
result note. A closed control never reopens; a correction is a new control.
The aggregate takes the clock as an argument and returns the new state; the use
case persists it in one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from insumap.domain.common.reason import Reason
from insumap.domain.common.text import invalid_field
from insumap.domain.identity.errors import InvalidStateTransitionError

MACHINE_NAME: Final = "follow_up"
SCHEDULED_FIELD: Final = "body.scheduled_at"
IN_THE_PAST: Final = "in_the_past"


class FollowUpStatus(StrEnum):
    """Status of a control (``care.follow_ups.status``, kind ``CONTROL``)."""

    SCHEDULED = "SCHEDULED"
    DONE = "DONE"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class FollowUpOutcome(StrEnum):
    """How a scheduled control ended: attended or missed."""

    DONE = "DONE"
    MISSED = "MISSED"


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUp:
    """A control of one patient, scheduled by a doctor (``care.follow_ups``)."""

    follow_up_id: UUID
    clinic_id: UUID
    patient_id: UUID
    status: FollowUpStatus
    scheduled_for: datetime
    assigned_to: UUID
    created_by: UUID
    title: str
    created_at: datetime
    result_note: str | None = None
    closed_at: datetime | None = None

    @classmethod
    def schedule(
        cls,
        *,
        follow_up_id: UUID,
        clinic_id: UUID,
        patient_id: UUID,
        scheduled_for: datetime,
        by: UUID,
        title: str,
        at: datetime,
    ) -> FollowUp:
        """A new control; its date must be after ``at`` (a ``422`` otherwise)."""
        if scheduled_for <= at:
            raise invalid_field(SCHEDULED_FIELD, IN_THE_PAST)
        return cls(
            follow_up_id=follow_up_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            status=FollowUpStatus.SCHEDULED,
            scheduled_for=scheduled_for,
            assigned_to=by,
            created_by=by,
            title=title,
            created_at=at,
        )

    def close(
        self, *, outcome: FollowUpOutcome, note: Reason, at: datetime
    ) -> FollowUp:
        """Close a scheduled control with its outcome and note (``409`` if closed)."""
        if self.status is not FollowUpStatus.SCHEDULED:
            raise InvalidStateTransitionError(MACHINE_NAME, self.status.value, "close")
        return replace(
            self,
            status=FollowUpStatus(outcome.value),
            result_note=note.text,
            closed_at=at,
        )
