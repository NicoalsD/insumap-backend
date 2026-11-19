"""Reminder commands and reads (P13, P11, C3) over in-memory doubles."""

from dataclasses import replace
from datetime import UTC, datetime, time
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.reminders.commands import (
    CreateReminderCommand,
    CreateReminderCommandHandler,
    UpdateOwnReminderCommand,
    UpdateOwnReminderCommandHandler,
    UpdatePatientReminderCommand,
    UpdatePatientReminderCommandHandler,
)
from insumap.application.reminders.queries import (
    ListOwnRemindersInput,
    ListOwnRemindersUseCase,
    ListPatientRemindersInput,
    ListPatientRemindersUseCase,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.reminders.reminder import (
    ReminderInvariantError,
    ReminderSchedule,
    ReminderType,
)
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds, FakeUnitOfWorkPort
from tests.support.monitoring_factories import PATIENT_ID, USER_ID
from tests.support.monitoring_fakes import (
    DOCTOR_ID,
    FakeConsentsGate,
    FakePatientRecords,
)
from tests.support.targets_fakes import CLINIC_ID, NOW, FakeReminders

OTHER_PATIENT = UUID(int=0xA3)
PATIENT_RIGHTS = frozenset(
    {PermissionCode.REMINDERS_MANAGE_OWN, PermissionCode.REMINDERS_MANAGE_ASSIGNED}
)
DOCTOR_RIGHTS = frozenset({PermissionCode.REMINDERS_MANAGE_ASSIGNED})
LATER = datetime(2026, 11, 19, 13, 0, tzinfo=UTC)


def doctor() -> Actor:
    return Actor(
        user_id=DOCTOR_ID,
        clinic_id=CLINIC_ID,
        role=Role.DOCTOR,
        permissions=DOCTOR_RIGHTS,
        requires_mfa=True,
        mfa_verified=True,
    )


def patient(permissions: frozenset[PermissionCode] = PATIENT_RIGHTS) -> Actor:
    return Actor(
        user_id=USER_ID,
        clinic_id=CLINIC_ID,
        role=Role.PATIENT,
        patient_id=PATIENT_ID,
        permissions=permissions,
    )


SCHEDULE = ReminderSchedule(local_time=time(7, 30), days_of_week=(1, 2, 3))


class World:
    def __init__(self) -> None:
        self.reminders = FakeReminders()
        self.patients = FakePatientRecords()
        self.consents = FakeConsentsGate()
        self.ids = FakeIds()
        self.clock = FixedClock(NOW)
        self.audit = InMemoryAuditLog()
        self.uow = FakeUnitOfWorkPort()

    def create(self, actor: Actor, patient_id: UUID = PATIENT_ID) -> UUID:
        handler = AuditingCommandHandler(
            CreateReminderCommandHandler(
                gate=AssignedPatientGate(self.patients),
                reminders=self.reminders,
                ids=self.ids,
                clock=self.clock,
            ),
            self.audit,
            self.clock,
        )
        return handler.handle(
            CreateReminderCommand(
                actor=actor,
                patient_id=patient_id,
                reminder_type=ReminderType.MEASUREMENT,
                schedule=SCHEDULE,
                is_active=True,
            )
        ).id


@pytest.fixture
def world() -> World:
    return World()


def test_doctor_schedules_a_reminder_for_an_assigned_patient(world: World) -> None:
    reminder_id = world.create(doctor())

    reminder = world.reminders.rows[reminder_id]
    assert reminder.patient_id == PATIENT_ID
    assert reminder.set_by == DOCTOR_ID
    assert reminder.message_key == "reminder.measurement"
    assert reminder.schedule == SCHEDULE
    assert [e.action for e in world.audit.entries] == ["REMINDER_CREATED"]


def test_doctor_cannot_schedule_for_an_unassigned_patient(world: World) -> None:
    with pytest.raises(InsumapError) as raised:
        world.create(doctor(), patient_id=OTHER_PATIENT)

    assert raised.value.code is ErrorCode.NOT_FOUND
    assert world.reminders.rows == {}


def test_create_rejects_an_invalid_schedule(world: World) -> None:
    handler = CreateReminderCommandHandler(
        gate=AssignedPatientGate(world.patients),
        reminders=world.reminders,
        ids=world.ids,
        clock=world.clock,
    )

    with pytest.raises(ReminderInvariantError):
        handler.handle(
            CreateReminderCommand(
                actor=doctor(),
                patient_id=PATIENT_ID,
                reminder_type=ReminderType.CONTROL,
                schedule=ReminderSchedule(local_time=time(8, 0), days_of_week=(9,)),
                is_active=True,
            )
        )


def test_doctor_update_of_another_patients_reminder_is_not_found(
    world: World,
) -> None:
    reminder_id = world.create(doctor())
    other = world.reminders.rows[reminder_id]
    world.reminders.rows[reminder_id] = replace(other, patient_id=OTHER_PATIENT)
    handler = UpdatePatientReminderCommandHandler(
        gate=AssignedPatientGate(world.patients),
        reminders=world.reminders,
        clock=world.clock,
    )

    with pytest.raises(ResourceNotFoundError):
        handler.handle(
            UpdatePatientReminderCommand(
                actor=doctor(),
                patient_id=PATIENT_ID,
                reminder_id=reminder_id,
                is_active=False,
            )
        )


def test_doctor_deactivates_a_reminder_of_the_patient(world: World) -> None:
    reminder_id = world.create(doctor())
    handler = UpdatePatientReminderCommandHandler(
        gate=AssignedPatientGate(world.patients),
        reminders=world.reminders,
        clock=world.clock,
    )

    updated = handler.handle(
        UpdatePatientReminderCommand(
            actor=doctor(),
            patient_id=PATIENT_ID,
            reminder_id=reminder_id,
            is_active=False,
        )
    )

    assert updated.is_active is False
    assert updated.schedule == SCHEDULE


def test_patient_adjusts_his_own_reminder(world: World) -> None:
    reminder_id = world.create(doctor())
    handler = UpdateOwnReminderCommandHandler(
        gate=OwnPatientGate(world.consents),
        reminders=world.reminders,
        clock=world.clock,
    )
    new_schedule = ReminderSchedule(local_time=time(9, 15))

    updated = handler.handle(
        UpdateOwnReminderCommand(
            actor=patient(),
            reminder_id=reminder_id,
            schedule=new_schedule,
        )
    )

    assert updated.schedule == new_schedule
    assert updated.updated_at == world.clock.now()


def test_patient_without_consent_cannot_adjust(world: World) -> None:
    reminder_id = world.create(doctor())
    world.consents.accepted = False
    handler = UpdateOwnReminderCommandHandler(
        gate=OwnPatientGate(world.consents),
        reminders=world.reminders,
        clock=world.clock,
    )

    with pytest.raises(ConsentRequiredError):
        handler.handle(
            UpdateOwnReminderCommand(
                actor=patient(), reminder_id=reminder_id, is_active=False
            )
        )


def test_patient_cannot_adjust_without_the_own_permission(world: World) -> None:
    reminder_id = world.create(doctor())
    handler = UpdateOwnReminderCommandHandler(
        gate=OwnPatientGate(world.consents),
        reminders=world.reminders,
        clock=world.clock,
    )

    with pytest.raises(PermissionDeniedError):
        handler.handle(
            UpdateOwnReminderCommand(
                actor=patient(frozenset()), reminder_id=reminder_id, is_active=False
            )
        )


def test_patient_list_is_paged_and_scoped_to_the_patient(world: World) -> None:
    for _ in range(3):
        world.create(doctor())
    someone_else = replace(
        next(iter(world.reminders.rows.values())),
        id=UUID(int=1),
        patient_id=OTHER_PATIENT,
    )
    world.reminders.rows[someone_else.id] = someone_else
    use_case = ListOwnRemindersUseCase(
        uow=world.uow, gate=OwnPatientGate(world.consents), reminders=world.reminders
    )

    first = use_case.execute(
        ListOwnRemindersInput(actor=patient(), page=PageRequest(limit=2))
    )

    assert len(first.items) == 2
    assert first.next_cursor is not None
    assert all(r.patient_id == PATIENT_ID for r in first.items)


def test_doctor_list_of_an_unassigned_patient_is_not_found(world: World) -> None:
    use_case = ListPatientRemindersUseCase(
        uow=world.uow,
        gate=AssignedPatientGate(world.patients),
        reminders=world.reminders,
    )

    with pytest.raises(InsumapError) as raised:
        use_case.execute(
            ListPatientRemindersInput(
                actor=doctor(), patient_id=OTHER_PATIENT, page=PageRequest(limit=5)
            )
        )

    assert raised.value.code is ErrorCode.NOT_FOUND
