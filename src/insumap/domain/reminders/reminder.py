"""Reminders of a patient: a local time on some weekdays (``care.reminder_schedules``).

The job that sends them evaluates every minute in the zone of the clinic; this
module only holds the schedule and its rules. The text of a reminder is a key of
``messages_es`` chosen by its type, so no reminder carries clinical data.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from enum import StrEnum
from typing import Final, final
from uuid import UUID

from insumap.shared.errors import ErrorCode, InsumapError

FIRST_WEEKDAY: Final = 1
"""ISO weekday of Monday; the calendar, not a clinical value."""
LAST_WEEKDAY: Final = 7
"""ISO weekday of Sunday. ``None`` days of week means every day."""

DAYS_OF_WEEK: Final = "days_of_week"
LOCAL_TIME: Final = "local_time"
INVALID_WEEKDAY: Final = "invalid_weekday"
DUPLICATE_WEEKDAY: Final = "duplicate_weekday"
EMPTY_WEEKDAYS: Final = "empty_weekdays"


class ReminderType(StrEnum):
    """What the reminder asks for (``ck_reminder_schedules_reminder_type``)."""

    MEASUREMENT = "MEASUREMENT"
    INSULIN_DOSE = "INSULIN_DOSE"
    CONTROL = "CONTROL"
    REGISTRATION = "REGISTRATION"


MESSAGE_KEY_BY_TYPE: Final[dict[ReminderType, str]] = {
    ReminderType.MEASUREMENT: "reminder.measurement",
    ReminderType.INSULIN_DOSE: "reminder.insulin_dose",
    ReminderType.CONTROL: "reminder.control",
    ReminderType.REGISTRATION: "reminder.registration",
}
"""Key of the text of each type in ``messages_es`` (no clinical data in it)."""


@final
class ReminderInvariantError(InsumapError):
    """The schedule breaks a rule; every broken rule is listed (422)."""

    def __init__(self, errors: tuple[tuple[str, str], ...]) -> None:
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [{"field": field, "type": kind} for field, kind in errors]
            },
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReminderSchedule:
    """A local time and the weekdays it applies to (``None``: every day)."""

    local_time: time
    days_of_week: tuple[int, ...] | None = None

    def ensure_valid(self) -> None:
        """Raise ``ReminderInvariantError`` if the weekdays are not a valid set."""
        if self.days_of_week is None:
            return
        errors: list[tuple[str, str]] = []
        if not self.days_of_week:
            errors.append((f"body.schedule.{DAYS_OF_WEEK}", EMPTY_WEEKDAYS))
        if len(set(self.days_of_week)) != len(self.days_of_week):
            errors.append((f"body.schedule.{DAYS_OF_WEEK}", DUPLICATE_WEEKDAY))
        if any(not FIRST_WEEKDAY <= day <= LAST_WEEKDAY for day in self.days_of_week):
            errors.append((f"body.schedule.{DAYS_OF_WEEK}", INVALID_WEEKDAY))
        if errors:
            raise ReminderInvariantError(tuple(errors))


@dataclass(frozen=True, slots=True, kw_only=True)
class Reminder:
    """One reminder of a patient, created by its doctor or adjusted by the patient."""

    id: UUID
    clinic_id: UUID
    patient_id: UUID
    reminder_type: ReminderType
    schedule: ReminderSchedule
    is_active: bool
    set_by: UUID
    created_at: datetime
    updated_at: datetime

    @property
    def message_key(self) -> str:
        return MESSAGE_KEY_BY_TYPE[self.reminder_type]

    def updated(
        self,
        *,
        schedule: ReminderSchedule | None,
        is_active: bool | None,
        at: datetime,
    ) -> Reminder:
        """The reminder with the fields given; the schedule is checked first."""
        if schedule is not None:
            schedule.ensure_valid()
        return replace(
            self,
            schedule=self.schedule if schedule is None else schedule,
            is_active=self.is_active if is_active is None else is_active,
            updated_at=at,
        )
