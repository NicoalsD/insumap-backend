"""``care.reminder_schedules``: the reminders of the patients of a clinic."""

from __future__ import annotations

from typing import final, override
from uuid import UUID

from sqlalchemy import select, update

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.reminders.ports import ReminderRepositoryPort
from insumap.domain.reminders.reminder import Reminder, ReminderSchedule, ReminderType
from insumap.infrastructure.persistence.metrics_orm import ReminderScheduleOrm
from insumap.infrastructure.persistence.transactions import CurrentSession


def _reminder(row: ReminderScheduleOrm) -> Reminder:
    days = row.days_of_week
    return Reminder(
        id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        reminder_type=ReminderType(row.reminder_type),
        schedule=ReminderSchedule(
            local_time=row.local_time,
            days_of_week=None if days is None else tuple(days),
        ),
        is_active=row.is_active,
        set_by=row.set_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@final
class ReminderRepository(ReminderRepositoryPort):
    """Reminders under row level security (the doctor's clinic, the patient's own)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, reminder_id: UUID) -> Reminder | None:
        row = self._current.get().get(ReminderScheduleOrm, reminder_id)
        return None if row is None else _reminder(row)

    @override
    def list_for_patient(self, patient_id: UUID, page: PageRequest) -> Page[Reminder]:
        statement = (
            select(ReminderScheduleOrm)
            .where(ReminderScheduleOrm.patient_id == patient_id)
            .order_by(ReminderScheduleOrm.id)
        )
        if page.after is not None:
            statement = statement.where(ReminderScheduleOrm.id > page.after)
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_reminder(row) for row in rows],
            limit=page.limit,
            key=lambda reminder: reminder.id,
        )

    @override
    def insert(self, reminder: Reminder) -> None:
        schedule = reminder.schedule
        self._current.get().add(
            ReminderScheduleOrm(
                id=reminder.id,
                clinic_id=reminder.clinic_id,
                patient_id=reminder.patient_id,
                plan_id=None,
                reminder_type=reminder.reminder_type.value,
                local_time=schedule.local_time,
                days_of_week=None
                if schedule.days_of_week is None
                else list(schedule.days_of_week),
                message_key=reminder.message_key,
                is_active=reminder.is_active,
                set_by=reminder.set_by,
                created_at=reminder.created_at,
                updated_at=reminder.updated_at,
            )
        )
        self._current.get().flush()

    @override
    def update(self, reminder: Reminder) -> None:
        schedule = reminder.schedule
        self._current.get().execute(
            update(ReminderScheduleOrm)
            .where(ReminderScheduleOrm.id == reminder.id)
            .values(
                local_time=schedule.local_time,
                days_of_week=None
                if schedule.days_of_week is None
                else list(schedule.days_of_week),
                is_active=reminder.is_active,
                updated_at=reminder.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
