"""Port of the reminders of a patient (``care.reminder_schedules``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.reminders.reminder import Reminder


class ReminderRepositoryPort(ABC):
    """Reminders under row level security: a doctor sees his clinic's, a patient his."""

    @abstractmethod
    def get(self, reminder_id: UUID) -> Reminder | None:
        """One reminder, or ``None`` if it does not exist or is not visible."""

    @abstractmethod
    def list_for_patient(self, patient_id: UUID, page: PageRequest) -> Page[Reminder]:
        """The reminders of a patient, by id."""

    @abstractmethod
    def insert(self, reminder: Reminder) -> None:
        """Insert a new reminder."""

    @abstractmethod
    def update(self, reminder: Reminder) -> None:
        """Write the schedule and the active flag of a reminder."""
