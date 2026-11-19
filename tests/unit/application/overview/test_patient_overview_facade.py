"""``PatientOverviewFacade`` (P10): the start page of an assigned or own patient."""

from dataclasses import replace
from uuid import UUID

import pytest

from insumap.application.metrics.metrics import MetricWindow
from insumap.application.overview.patient_overview_facade import PatientOverviewFacade
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.alerts_fakes import FakeAlerts
from tests.support.dashboard_fakes import FakeOpenAlerts
from tests.support.monitoring_factories import NOW, PATIENT_ID, make_reading
from tests.support.monitoring_fakes import (
    OTHER_PATIENT_ID,
    RecordsWorld,
    doctor_actor,
    patient_actor,
)
from tests.support.targets_fakes import FakeReminders
from tests.support.treatment_fakes import FakePlans


@pytest.fixture
def world() -> RecordsWorld:
    return RecordsWorld()


def build(
    world: RecordsWorld, *, open_alerts: dict[UUID, int] | None = None
) -> PatientOverviewFacade:
    return PatientOverviewFacade(
        uow=world.uow,
        assigned=world.assigned_gate,
        own=world.own_gate,
        targets=world.targets,
        series=world.series,
        readings=world.readings,
        plans=FakePlans(),
        alerts=FakeAlerts(),
        open_alerts=FakeOpenAlerts(open_alerts or {}),
        reminders=FakeReminders(),
        strategies=GlycemicTargetStrategyRegistry(),
        clock=world.clock,
    )


def doctor_permissions() -> frozenset[PermissionCode]:
    return frozenset({PermissionCode.PATIENTS_READ_ASSIGNED})


def test_the_doctor_sees_recent_readings_with_their_target(world: RecordsWorld) -> None:
    world.readings.add(make_reading(1, mg_dl="150", at=NOW))

    overview = build(world).for_assigned(
        doctor_actor(permissions=doctor_permissions()),
        PATIENT_ID,
        MetricWindow.LAST_14_DAYS,
    )

    assert overview.patient_id == PATIENT_ID
    assert [r.value_mg_dl for r in overview.recent_readings] == [150]
    assert overview.profile.code
    assert overview.open_alerts_count == 0
    assert overview.active_plan is None
    assert overview.simulated is False


def test_the_doctor_reads_an_assigned_patient_under_one_audited_transaction(
    world: RecordsWorld,
) -> None:
    build(world).for_assigned(
        doctor_actor(permissions=doctor_permissions()),
        PATIENT_ID,
        MetricWindow.LAST_14_DAYS,
    )

    assert world.patients.reads
    assert world.uow.commits == 1


def test_an_unassigned_patient_is_not_found(world: RecordsWorld) -> None:
    with pytest.raises(InsumapError) as error:
        build(world).for_assigned(
            doctor_actor(permissions=doctor_permissions()),
            OTHER_PATIENT_ID,
            MetricWindow.LAST_14_DAYS,
        )

    assert error.value.code is ErrorCode.NOT_FOUND


def test_a_caller_without_the_permission_is_forbidden(world: RecordsWorld) -> None:
    with pytest.raises(PermissionDeniedError):
        build(world).for_assigned(
            doctor_actor(permissions=frozenset()),
            PATIENT_ID,
            MetricWindow.LAST_14_DAYS,
        )


def test_the_open_alerts_come_from_the_count_port(world: RecordsWorld) -> None:
    overview = build(world, open_alerts={PATIENT_ID: 3}).for_assigned(
        doctor_actor(permissions=doctor_permissions()),
        PATIENT_ID,
        MetricWindow.LAST_14_DAYS,
    )

    assert overview.open_alerts_count == 3


def test_the_own_overview_needs_the_patient_to_have_consented(
    world: RecordsWorld,
) -> None:
    world.consents.accepted = False
    actor = patient_actor(permissions=frozenset({PermissionCode.PATIENTS_READ_OWN}))

    with pytest.raises(ConsentRequiredError):
        build(world).for_own(actor, MetricWindow.LAST_14_DAYS)


def test_the_own_overview_is_the_patient_of_the_token(world: RecordsWorld) -> None:
    actor = patient_actor(permissions=frozenset({PermissionCode.PATIENTS_READ_OWN}))

    overview = build(world).for_own(actor, MetricWindow.LAST_14_DAYS)

    assert overview.patient_id == PATIENT_ID


def test_a_demo_clinic_marks_its_overview_as_simulated(world: RecordsWorld) -> None:
    actor = replace(
        patient_actor(permissions=frozenset({PermissionCode.PATIENTS_READ_OWN})),
        clinic_is_demo=True,
    )

    assert build(world).for_own(actor, MetricWindow.LAST_14_DAYS).simulated is True


def test_a_missing_profile_is_a_setup_error(world: RecordsWorld) -> None:
    world.targets.targets = None

    with pytest.raises(InsumapError) as error:
        build(world).for_own(
            patient_actor(permissions=frozenset({PermissionCode.PATIENTS_READ_OWN})),
            MetricWindow.LAST_14_DAYS,
        )

    assert error.value.code is ErrorCode.INTERNAL_ERROR
