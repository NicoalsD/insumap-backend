"""Follow-up commands and reads (RF-86, P11, P13) over in-memory doubles."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.common.patient_scope import PatientScope
from insumap.application.follow_ups.commands import (
    CloseFollowUpCommand,
    CloseFollowUpCommandHandler,
    CreateFollowUpCommand,
    CreateFollowUpCommandHandler,
)
from insumap.application.follow_ups.queries import (
    ListFollowUpsInput,
    ListFollowUpsUseCase,
)
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.follow_ups.follow_up import (
    FollowUp,
    FollowUpOutcome,
    FollowUpStatus,
)
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.i18n import MessageCatalog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds, FakeUnitOfWorkPort
from tests.support.messaging_fakes import (
    NOW,
    OTHER_PATIENT,
    PATIENT,
    FakeAssignedRecords,
    FakeFollowUps,
    admin_actor,
    doctor_actor,
    patient_actor,
)
from tests.support.monitoring_fakes import FakeConsentsGate

DOCTOR_ID = doctor_actor().user_id
NOTE = "Asistió y se revisó la rutina"


class World:
    def __init__(self) -> None:
        self.follow_ups = FakeFollowUps()
        self.records = FakeAssignedRecords((DOCTOR_ID, PATIENT))
        self.assigned = AssignedPatientGate(self.records)
        self.clock = FixedClock(NOW)
        self.ids = FakeIds()
        self.catalog = MessageCatalog.load_spanish()

    def create(self, actor: Actor, patient_id: UUID, days: int = 3) -> FollowUp:
        handler = CreateFollowUpCommandHandler(
            gate=self.assigned,
            follow_ups=self.follow_ups,
            ids=self.ids,
            clock=self.clock,
            catalog=self.catalog,
        )
        return handler.handle(
            CreateFollowUpCommand(
                actor=actor,
                patient_id=patient_id,
                scheduled_for=NOW + timedelta(days=days),
            )
        )

    def close(self, actor: Actor, follow_up_id: UUID) -> FollowUp:
        handler = CloseFollowUpCommandHandler(
            gate=self.assigned, follow_ups=self.follow_ups, clock=self.clock
        )
        return handler.handle(
            CloseFollowUpCommand(
                actor=actor,
                follow_up_id=follow_up_id,
                outcome=FollowUpOutcome.DONE,
                result_note=NOTE,
            )
        )


@pytest.fixture
def world() -> World:
    return World()


def test_doctor_schedules_a_control_for_an_assigned_patient(world: World) -> None:
    control = world.create(doctor_actor(), PATIENT)

    assert control.status is FollowUpStatus.SCHEDULED
    assert world.follow_ups.rows[control.follow_up_id] == control
    assert world.records.reads[-1][1] == PATIENT


def test_scheduling_for_an_unassigned_patient_is_not_found(world: World) -> None:
    with pytest.raises(ResourceNotFoundError):
        world.create(doctor_actor(), OTHER_PATIENT)

    assert world.follow_ups.rows == {}


def test_clinic_admin_cannot_schedule(world: World) -> None:
    with pytest.raises(PermissionDeniedError):
        world.create(admin_actor(), PATIENT)


def test_closing_a_control_stores_the_result(world: World) -> None:
    control = world.create(doctor_actor(), PATIENT)

    closed = world.close(doctor_actor(), control.follow_up_id)

    assert closed.status is FollowUpStatus.DONE
    assert world.follow_ups.rows[control.follow_up_id].result_note == NOTE


def test_closing_twice_is_an_invalid_state_transition(world: World) -> None:
    control = world.create(doctor_actor(), PATIENT)
    world.close(doctor_actor(), control.follow_up_id)

    with pytest.raises(InvalidStateTransitionError):
        world.close(doctor_actor(), control.follow_up_id)


def test_closing_an_unknown_control_is_not_found(world: World) -> None:
    with pytest.raises(ResourceNotFoundError):
        world.close(doctor_actor(), UUID(int=999))


def test_short_result_note_is_refused_before_loading(world: World) -> None:
    control = world.create(doctor_actor(), PATIENT)
    handler = CloseFollowUpCommandHandler(
        gate=world.assigned, follow_ups=world.follow_ups, clock=world.clock
    )

    with pytest.raises(InsumapError) as error:
        handler.handle(
            CloseFollowUpCommand(
                actor=doctor_actor(),
                follow_up_id=control.follow_up_id,
                outcome=FollowUpOutcome.DONE,
                result_note="corto",
            )
        )

    assert error.value.code is ErrorCode.REASON_REQUIRED


def test_patient_lists_its_own_controls_without_an_audit_read(world: World) -> None:
    world.create(doctor_actor(), PATIENT)
    reads_before = len(world.records.reads)
    listing = ListFollowUpsUseCase(
        uow=FakeUnitOfWorkPort(),
        scope=PatientScope(
            assigned=world.assigned, own=OwnPatientGate(FakeConsentsGate())
        ),
        follow_ups=world.follow_ups,
    ).execute(
        ListFollowUpsInput(
            actor=patient_actor(),
            patient_id=None,
            status=None,
            page=PageRequest(limit=20),
        )
    )

    assert len(listing.items) == 1
    # The patient's own read goes through the consent gate, never the access chain.
    assert len(world.records.reads) == reads_before
