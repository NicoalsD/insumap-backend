"""Decisions about the reminders: the doctor schedules, the patient adjusts (P13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.reminders.ports import ReminderRepositoryPort
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.reminders.reminder import Reminder, ReminderSchedule, ReminderType
from insumap.shared.time import Clock

ENTITY: str = "REMINDER_SCHEDULE"


def _changed_fields(
    schedule: ReminderSchedule | None, is_active: bool | None
) -> tuple[str, ...]:
    fields: list[str] = []
    if schedule is not None:
        fields.extend(["local_time", "days_of_week"])
    if is_active is not None:
        fields.append("is_active")
    return tuple(fields)


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateReminderCommand(Command[Reminder]):
    """The doctor schedules a reminder for a patient he cares for."""

    audit_action: ClassVar[str] = "REMINDER_CREATED"
    audit_entity_type: ClassVar[str] = ENTITY

    patient_id: UUID
    reminder_type: ReminderType
    schedule: ReminderSchedule
    is_active: bool

    @override
    def audit_subject(self, result: Reminder) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.id,
            changed_fields=("reminder_type", "local_time", "days_of_week", "is_active"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdatePatientReminderCommand(Command[Reminder]):
    """The doctor changes the schedule or the active flag of a patient's reminder."""

    audit_action: ClassVar[str] = "REMINDER_UPDATED"
    audit_entity_type: ClassVar[str] = ENTITY

    patient_id: UUID
    reminder_id: UUID
    schedule: ReminderSchedule | None = None
    is_active: bool | None = None

    @override
    def audit_subject(self, result: Reminder) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.id,
            changed_fields=_changed_fields(self.schedule, self.is_active),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateOwnReminderCommand(Command[Reminder]):
    """The patient adjusts his own reminder (consent required, C3)."""

    audit_action: ClassVar[str] = "REMINDER_UPDATED"
    audit_entity_type: ClassVar[str] = ENTITY

    reminder_id: UUID
    schedule: ReminderSchedule | None = None
    is_active: bool | None = None

    @override
    def audit_subject(self, result: Reminder) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.id,
            changed_fields=_changed_fields(self.schedule, self.is_active),
        )


@final
class CreateReminderCommandHandler(CommandHandler[CreateReminderCommand, Reminder]):
    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        reminders: ReminderRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._reminders = reminders
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateReminderCommand) -> Reminder:
        actor = command.actor
        patient_id = self._gate.enter(
            actor,
            PermissionCode.REMINDERS_MANAGE_ASSIGNED,
            command.patient_id,
            DataResource.TREATMENT_PLAN,
        )
        if actor.clinic_id is None:
            raise PermissionDeniedError
        command.schedule.ensure_valid()
        at = self._clock.now()
        reminder = Reminder(
            id=self._ids.new_id(),
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            reminder_type=command.reminder_type,
            schedule=command.schedule,
            is_active=command.is_active,
            set_by=actor.user_id,
            created_at=at,
            updated_at=at,
        )
        self._reminders.insert(reminder)
        return reminder


@final
class UpdatePatientReminderCommandHandler(
    CommandHandler[UpdatePatientReminderCommand, Reminder]
):
    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        reminders: ReminderRepositoryPort,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._reminders = reminders
        self._clock = clock

    @override
    def handle(self, command: UpdatePatientReminderCommand) -> Reminder:
        patient_id = self._gate.enter(
            command.actor,
            PermissionCode.REMINDERS_MANAGE_ASSIGNED,
            command.patient_id,
            DataResource.TREATMENT_PLAN,
        )
        current = self._reminders.get(command.reminder_id)
        if current is None or current.patient_id != patient_id:
            raise ResourceNotFoundError
        updated = current.updated(
            schedule=command.schedule,
            is_active=command.is_active,
            at=self._clock.now(),
        )
        self._reminders.update(updated)
        return updated


@final
class UpdateOwnReminderCommandHandler(
    CommandHandler[UpdateOwnReminderCommand, Reminder]
):
    def __init__(
        self,
        *,
        gate: OwnPatientGate,
        reminders: ReminderRepositoryPort,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._reminders = reminders
        self._clock = clock

    @override
    def handle(self, command: UpdateOwnReminderCommand) -> Reminder:
        scope = self._gate.enter(command.actor, PermissionCode.REMINDERS_MANAGE_OWN)
        current = self._reminders.get(command.reminder_id)
        if current is None or current.patient_id != scope.patient_id:
            raise ResourceNotFoundError
        updated = current.updated(
            schedule=command.schedule,
            is_active=command.is_active,
            at=self._clock.now(),
        )
        self._reminders.update(updated)
        return updated
