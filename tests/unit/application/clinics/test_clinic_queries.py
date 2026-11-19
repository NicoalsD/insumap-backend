"""Clinic reads (API.md 8.3): the platform reads all, staff reads only their own."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.clinics.queries import (
    GetClinicInput,
    GetClinicUseCase,
    GetCurrentClinicInput,
    GetCurrentClinicUseCase,
    ListClinicsInput,
    ListClinicsUseCase,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.domain.clinic.clinic import Clinic, ClinicStatus
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.support.clinic_fakes import FakeClinics
from tests.support.identity_fakes import FakeUnitOfWorkPort

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
PLATFORM = UUID(int=1)
CLINIC_A = UUID(int=100)
CLINIC_B = UUID(int=200)
STAFF = UUID(int=300)
PAGE = PageRequest(limit=20)
SUSPENSION_REASON = "Suspensión por revisión de contrato"


def clinic(clinic_id: UUID, name: str, *, suspended: bool = False) -> Clinic:
    created = Clinic.create(
        clinic_id=clinic_id,
        name=name,
        tax_id="900000001",
        timezone="America/Bogota",
        is_demo=False,
        at=NOW,
    )
    if suspended:
        return created.suspended(reason=Reason.parse(SUSPENSION_REASON), at=NOW)
    return created


def platform() -> Actor:
    return Actor(
        user_id=PLATFORM,
        clinic_id=None,
        role=Role.PLATFORM_ADMIN,
        permissions=frozenset({PermissionCode.CLINICS_MANAGE}),
        requires_mfa=True,
        mfa_verified=True,
    )


def staff(clinic_id: UUID | None, *permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=STAFF,
        clinic_id=clinic_id,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset(permissions),
        requires_mfa=True,
        mfa_verified=True,
    )


@pytest.fixture
def clinics() -> FakeClinics:
    return FakeClinics(
        clinic(CLINIC_A, "Clínica Norte"),
        clinic(CLINIC_B, "Clínica Sur", suspended=True),
    )


def test_platform_lists_every_clinic(clinics: FakeClinics) -> None:
    page = ListClinicsUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
        ListClinicsInput(actor=platform(), status=None, is_demo=None, page=PAGE)
    )

    assert [c.clinic_id for c in page.items] == [CLINIC_A, CLINIC_B]
    assert page.next_cursor is None


def test_listing_filters_by_status(clinics: FakeClinics) -> None:
    page = ListClinicsUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
        ListClinicsInput(
            actor=platform(), status=ClinicStatus.SUSPENDED, is_demo=None, page=PAGE
        )
    )

    assert [c.clinic_id for c in page.items] == [CLINIC_B]


def test_listing_requires_clinics_manage(clinics: FakeClinics) -> None:
    actor = staff(CLINIC_A, PermissionCode.CLINICS_READ)

    with pytest.raises(PermissionDeniedError):
        ListClinicsUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
            ListClinicsInput(actor=actor, status=None, is_demo=None, page=PAGE)
        )


def test_get_returns_the_clinic_with_its_suspension(clinics: FakeClinics) -> None:
    found = GetClinicUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
        GetClinicInput(actor=platform(), clinic_id=CLINIC_B)
    )

    assert found.status is ClinicStatus.SUSPENDED
    assert found.suspended_reason == SUSPENSION_REASON


def test_get_of_an_unknown_clinic_is_not_found(clinics: FakeClinics) -> None:
    with pytest.raises(ResourceNotFoundError):
        GetClinicUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
            GetClinicInput(actor=platform(), clinic_id=UUID(int=999))
        )


def test_current_is_the_clinic_of_the_token(clinics: FakeClinics) -> None:
    actor = staff(CLINIC_A, PermissionCode.CLINICS_READ)

    found = GetCurrentClinicUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
        GetCurrentClinicInput(actor=actor)
    )

    assert found.clinic_id == CLINIC_A


def test_current_requires_clinics_read(clinics: FakeClinics) -> None:
    with pytest.raises(PermissionDeniedError):
        GetCurrentClinicUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
            GetCurrentClinicInput(actor=platform())
        )


def test_current_without_a_clinic_is_not_found(clinics: FakeClinics) -> None:
    actor = staff(None, PermissionCode.CLINICS_READ)

    with pytest.raises(ResourceNotFoundError):
        GetCurrentClinicUseCase(uow=FakeUnitOfWorkPort(), clinics=clinics).execute(
            GetCurrentClinicInput(actor=actor)
        )


def test_current_reads_under_the_actor_context(clinics: FakeClinics) -> None:
    uow = FakeUnitOfWorkPort()
    actor = staff(CLINIC_A, PermissionCode.CLINICS_READ)

    GetCurrentClinicUseCase(uow=uow, clinics=clinics).execute(
        GetCurrentClinicInput(actor=actor)
    )

    assert uow.contexts[-1].clinic_id == CLINIC_A
    assert uow.contexts[-1].role is Role.CLINIC_ADMIN
