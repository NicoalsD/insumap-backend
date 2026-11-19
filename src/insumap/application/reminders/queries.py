"""Reads of the reminders (API.md 8.7): the doctor's view and the patient's own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.reminders.ports import ReminderRepositoryPort
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.reminders.reminder import Reminder


@dataclass(frozen=True, slots=True, kw_only=True)
class ListPatientRemindersInput:
    actor: Actor
    patient_id: UUID
    page: PageRequest


@final
class ListPatientRemindersUseCase:
    """The reminders of an assigned patient; other patients answer ``404``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: AssignedPatientGate,
        reminders: ReminderRepositoryPort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._reminders = reminders

    def execute(self, input: ListPatientRemindersInput) -> Page[Reminder]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            patient_id = self._gate.enter(
                input.actor,
                PermissionCode.REMINDERS_MANAGE_ASSIGNED,
                input.patient_id,
                DataResource.TREATMENT_PLAN,
            )
            return self._reminders.list_for_patient(patient_id, input.page)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListOwnRemindersInput:
    actor: Actor
    page: PageRequest


@final
class ListOwnRemindersUseCase:
    """The reminders of the patient of the token (consent required)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        reminders: ReminderRepositoryPort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._reminders = reminders

    def execute(self, input: ListOwnRemindersInput) -> Page[Reminder]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            scope = self._gate.enter(input.actor, PermissionCode.REMINDERS_MANAGE_OWN)
            return self._reminders.list_for_patient(scope.patient_id, input.page)
