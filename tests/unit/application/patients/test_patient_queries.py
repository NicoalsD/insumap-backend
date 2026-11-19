"""``GET /patients`` and ``GET /patients/{id}``: scope, filters and the audit row."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessOutcome,
    DataResource,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.patients.ports import (
    PatientAdministrativeView,
    PatientRosterFilter,
)
from insumap.application.patients.queries import (
    GetPatientInput,
    GetPatientUseCase,
    ListPatientsInput,
    ListPatientsUseCase,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.invitation import InvitationStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.support.access_fakes import CLINIC, InMemoryDataAccessLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeUnitOfWorkPort
from tests.support.patient_fakes import FakePatientRoster

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
ADMIN = UUID(int=3)
DOCTOR = UUID(int=1)
OTHER_CLINIC = UUID(int=99)
PATIENT_A = UUID(int=100)
PATIENT_B = UUID(int=101)
PATIENT_OTHER_CLINIC = UUID(int=102)
ROSTER_PERMISSIONS = frozenset({PermissionCode.PATIENTS_READ_ROSTER})


def admin(permissions: frozenset[PermissionCode] = ROSTER_PERMISSIONS) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=CLINIC,
        role=Role.CLINIC_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


def view(
    patient_id: UUID,
    *,
    clinic_id: UUID = CLINIC,
    status: AccountStatus = AccountStatus.ACTIVE,
    doctors: int = 1,
) -> PatientAdministrativeView:
    return PatientAdministrativeView(
        patient_id=patient_id,
        clinic_id=clinic_id,
        full_name="Paciente de Prueba Uno",
        mrn=f"DEMO-{patient_id.int:04d}",
        document_last4="1234",
        account_status=status,
        primary_doctor_id=DOCTOR if doctors else None,
        assigned_doctor_count=doctors,
        invitation_status=InvitationStatus.PENDING,
        simulated=True,
    )


def roster() -> FakePatientRoster:
    return FakePatientRoster(
        view(PATIENT_A),
        view(PATIENT_B, status=AccountStatus.SUSPENDED, doctors=0),
        view(PATIENT_OTHER_CLINIC, clinic_id=OTHER_CLINIC),
    )


class ListWorld:
    def __init__(self, fake: FakePatientRoster | None = None) -> None:
        self.uow = FakeUnitOfWorkPort()
        self.log = InMemoryDataAccessLog()
        self.roster = fake or roster()
        self.use_case = ListPatientsUseCase(
            uow=self.uow,
            roster=self.roster,
            access_log=self.log,
            clock=FixedClock(NOW),
        )


class DetailWorld:
    def __init__(self, fake: FakePatientRoster | None = None) -> None:
        self.uow = FakeUnitOfWorkPort()
        self.log = InMemoryDataAccessLog()
        self.roster = fake or roster()
        self.use_case = GetPatientUseCase(
            uow=self.uow,
            roster=self.roster,
            access_log=self.log,
            clock=FixedClock(NOW),
        )


def test_list_returns_only_the_clinic_and_writes_one_patient_list_row() -> None:
    world = ListWorld()

    page = world.use_case.execute(
        ListPatientsInput(
            actor=admin(),
            filters=PatientRosterFilter(),
            page=PageRequest(limit=10),
        )
    )

    assert [item.patient_id for item in page.items] == [PATIENT_A, PATIENT_B]
    assert page.next_cursor is None
    assert len(world.log.granted) == 1
    row = world.log.granted[0]
    assert row.resource is DataResource.PATIENT_LIST
    assert row.purpose is AccessPurpose.ADMINISTRATION
    assert row.outcome is DataAccessOutcome.GRANTED
    assert row.patient_id is None
    assert row.clinic_id == CLINIC


def test_list_applies_the_status_and_without_doctor_filters() -> None:
    world = ListWorld()

    suspended = world.use_case.execute(
        ListPatientsInput(
            actor=admin(),
            filters=PatientRosterFilter(account_status=AccountStatus.SUSPENDED),
            page=PageRequest(limit=10),
        )
    )
    unassigned = world.use_case.execute(
        ListPatientsInput(
            actor=admin(),
            filters=PatientRosterFilter(without_doctor=True),
            page=PageRequest(limit=10),
        )
    )

    assert [item.patient_id for item in suspended.items] == [PATIENT_B]
    assert [item.patient_id for item in unassigned.items] == [PATIENT_B]


def test_list_pages_with_a_cursor() -> None:
    world = ListWorld()

    first = world.use_case.execute(
        ListPatientsInput(
            actor=admin(), filters=PatientRosterFilter(), page=PageRequest(limit=1)
        )
    )
    assert first.next_cursor is not None
    second = world.use_case.execute(
        ListPatientsInput(
            actor=admin(),
            filters=PatientRosterFilter(),
            page=PageRequest(limit=1, after=PATIENT_A),
        )
    )

    assert [item.patient_id for item in first.items] == [PATIENT_A]
    assert [item.patient_id for item in second.items] == [PATIENT_B]


def test_list_without_the_permission_is_forbidden_and_reads_nothing() -> None:
    world = ListWorld()

    with pytest.raises(PermissionDeniedError):
        world.use_case.execute(
            ListPatientsInput(
                actor=admin(frozenset()),
                filters=PatientRosterFilter(),
                page=PageRequest(limit=10),
            )
        )

    assert world.log.granted == []


def test_detail_returns_the_view_and_writes_a_demographics_row() -> None:
    world = DetailWorld()

    found = world.use_case.execute(GetPatientInput(actor=admin(), patient_id=PATIENT_A))

    assert found.patient_id == PATIENT_A
    assert found.document_last4 == "1234"
    row = world.log.granted[0]
    assert row.resource is DataResource.PATIENT_DEMOGRAPHICS
    assert row.patient_id == PATIENT_A


@pytest.mark.parametrize("patient_id", [PATIENT_OTHER_CLINIC, UUID(int=404)])
def test_detail_of_another_clinic_or_missing_is_the_same_not_found(
    patient_id: UUID,
) -> None:
    world = DetailWorld()

    with pytest.raises(ResourceNotFoundError):
        world.use_case.execute(GetPatientInput(actor=admin(), patient_id=patient_id))

    assert world.log.granted == []
    assert len(world.log.denied) == 1
    assert world.log.denied[0].outcome is DataAccessOutcome.DENIED
    assert world.log.denied[0].resource is DataResource.PATIENT_DEMOGRAPHICS


def test_detail_without_the_permission_is_forbidden_before_the_lookup() -> None:
    world = DetailWorld()

    with pytest.raises(PermissionDeniedError):
        world.use_case.execute(
            GetPatientInput(actor=admin(frozenset()), patient_id=PATIENT_A)
        )

    assert world.log.granted == []
    assert world.log.denied == []


def test_other_clinic_id_in_the_actor_is_not_used_for_the_lookup() -> None:
    """The clinic comes from the token: a view of another clinic stays hidden."""
    world = DetailWorld()
    stranger = Actor(
        user_id=DOCTOR,
        clinic_id=OTHER_CLINIC,
        role=Role.CLINIC_ADMIN,
        permissions=ROSTER_PERMISSIONS,
        requires_mfa=True,
        mfa_verified=True,
    )

    with pytest.raises(ResourceNotFoundError):
        world.use_case.execute(GetPatientInput(actor=stranger, patient_id=PATIENT_A))
