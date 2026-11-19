"""Schedule rules and updates of a reminder (no database)."""

from datetime import UTC, datetime, time
from uuid import UUID

import pytest

from insumap.domain.reminders.reminder import (
    DUPLICATE_WEEKDAY,
    EMPTY_WEEKDAYS,
    INVALID_WEEKDAY,
    MESSAGE_KEY_BY_TYPE,
    Reminder,
    ReminderInvariantError,
    ReminderSchedule,
    ReminderType,
)
from insumap.shared.i18n import MessageCatalog

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 19, 13, 0, tzinfo=UTC)


def reminder() -> Reminder:
    return Reminder(
        id=UUID(int=1),
        clinic_id=UUID(int=2),
        patient_id=UUID(int=3),
        reminder_type=ReminderType.MEASUREMENT,
        schedule=ReminderSchedule(local_time=time(7, 30), days_of_week=(1, 3, 5)),
        is_active=True,
        set_by=UUID(int=4),
        created_at=NOW,
        updated_at=NOW,
    )


def test_every_day_is_a_schedule_without_weekdays() -> None:
    ReminderSchedule(local_time=time(8, 0), days_of_week=None).ensure_valid()


@pytest.mark.parametrize(
    ("days", "kind"),
    [
        ((), EMPTY_WEEKDAYS),
        ((1, 1), DUPLICATE_WEEKDAY),
        ((0,), INVALID_WEEKDAY),
        ((8,), INVALID_WEEKDAY),
    ],
)
def test_weekdays_are_a_non_empty_unique_set_within_the_calendar(
    days: tuple[int, ...], kind: str
) -> None:
    with pytest.raises(ReminderInvariantError) as raised:
        ReminderSchedule(local_time=time(8, 0), days_of_week=days).ensure_valid()

    assert raised.value.detail["errors"] == [
        {"field": "body.schedule.days_of_week", "type": kind}
    ]


def test_update_changes_only_the_fields_given() -> None:
    changed = reminder().updated(schedule=None, is_active=False, at=LATER)

    assert changed.is_active is False
    assert changed.schedule == reminder().schedule
    assert changed.updated_at == LATER


def test_update_with_an_invalid_schedule_keeps_the_reminder_unchanged() -> None:
    bad = ReminderSchedule(local_time=time(9, 0), days_of_week=(9,))

    with pytest.raises(ReminderInvariantError):
        reminder().updated(schedule=bad, is_active=None, at=LATER)


def test_message_key_follows_the_type_and_exists_in_the_catalog() -> None:
    catalog = MessageCatalog.load_spanish()

    assert set(MESSAGE_KEY_BY_TYPE) == set(ReminderType)
    for key in MESSAGE_KEY_BY_TYPE.values():
        assert catalog.render(key).strip()
    assert reminder().message_key == "reminder.measurement"
