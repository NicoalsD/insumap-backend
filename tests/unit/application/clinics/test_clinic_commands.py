"""Clinic commands (P13) behind the audit decorator (P09), without a database."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from insumap.application.clinics.commands import (
    CreateClinicCommand,
    CreateClinicCommandHandler,
    ReactivateClinicCommand,
    ReactivateClinicCommandHandler,
    SuspendClinicCommand,
    SuspendClinicCommandHandler,
    UpdateClinicCommand,
    UpdateClinicCommandHandler,
)
from insumap.application.clinics.ports import ClinicRepositoryPort
from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import InMemoryCommandBus, bind
from insumap.application.common.actor import Actor
from insumap.domain.clinic.clinic import Clinic, ClinicStatus
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.errors import InsumapError
from tests.support.clinic_fakes import FakeClinics
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
PLATFORM = UUID(int=1)
CLINIC = UUID(int=100)
REASON = "Revisión de contrato con la clínica"


def platform(*permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=PLATFORM,
        clinic_id=None,
        role=Role.PLATFORM_ADMIN,
        permissions=frozenset(permissions or {PermissionCode.CLINICS_MANAGE}),
        requires_mfa=True,
        mfa_verified=True,
    )


def existing(*, suspended: bool = False) -> Clinic:
    clinic = Clinic.create(
        clinic_id=CLINIC,
        name="Clínica Norte",
        tax_id="900000001",
        timezone="America/Bogota",
        is_demo=False,
        at=NOW,
    )
    if suspended:
        return clinic.suspended(reason=Reason.parse(REASON), at=NOW)
    return clinic


class Harness:
    """A command bus with every clinic handler, each behind the audit decorator."""

    def __init__(self, clinics: ClinicRepositoryPort) -> None:
        self.clinics = clinics
        self.audit = InMemoryAuditLog()
        clock = FixedClock(NOW)
        ids = FakeIds()

        def audited(handler: Any) -> Any:
            return AuditingCommandHandler(handler, self.audit, clock)

        self.bus = InMemoryCommandBus(
            [
                bind(
                    CreateClinicCommand,
                    audited(
                        CreateClinicCommandHandler(
                            clinics=clinics, ids=ids, clock=clock
                        )
                    ),
                ),
                bind(
                    UpdateClinicCommand,
                    audited(UpdateClinicCommandHandler(clinics=clinics, clock=clock)),
                ),
                bind(
                    SuspendClinicCommand,
                    audited(SuspendClinicCommandHandler(clinics=clinics, clock=clock)),
                ),
                bind(
                    ReactivateClinicCommand,
                    audited(
                        ReactivateClinicCommandHandler(clinics=clinics, clock=clock)
                    ),
                ),
            ]
        )


def test_create_stores_an_active_clinic_and_audits_it() -> None:
    clinics = FakeClinics()
    harness = Harness(clinics)

    clinic = harness.bus.dispatch(
        CreateClinicCommand(
            actor=platform(),
            name="Clínica Sur",
            tax_id="900000002",
            timezone="America/Bogota",
            is_demo=True,
        )
    )

    assert clinic.status is ClinicStatus.ACTIVE
    assert clinics.rows[clinic.clinic_id] == clinic
    [entry] = harness.audit.entries
    assert entry.action == "CLINIC_CREATED"
    assert entry.clinic_id == clinic.clinic_id
    assert entry.changed_fields == ("name", "tax_id", "timezone", "is_demo")


def test_create_requires_clinics_manage() -> None:
    harness = Harness(FakeClinics())

    with pytest.raises(PermissionDeniedError):
        harness.bus.dispatch(
            CreateClinicCommand(
                actor=platform(PermissionCode.CLINICS_READ),
                name="Clínica Sur",
                tax_id="900000002",
                timezone="America/Bogota",
                is_demo=False,
            )
        )
    assert harness.audit.entries == []


def test_create_with_an_unknown_timezone_is_a_validation_error() -> None:
    harness = Harness(FakeClinics())

    with pytest.raises(InsumapError) as refused:
        harness.bus.dispatch(
            CreateClinicCommand(
                actor=platform(),
                name="Clínica Sur",
                tax_id="900000002",
                timezone="Mars/Olympus",
                is_demo=False,
            )
        )

    assert refused.value.code.value == "VALIDATION_ERROR"


def test_a_repeated_name_ignoring_case_is_a_conflict() -> None:
    clinics = FakeClinics(existing())
    harness = Harness(clinics)

    with pytest.raises(ConflictError):
        harness.bus.dispatch(
            CreateClinicCommand(
                actor=platform(),
                name="CLÍNICA NORTE",
                tax_id="900000003",
                timezone="America/Bogota",
                is_demo=False,
            )
        )


def test_update_changes_only_the_fields_given() -> None:
    clinics = FakeClinics(existing())
    harness = Harness(clinics)

    updated = harness.bus.dispatch(
        UpdateClinicCommand(
            actor=platform(),
            clinic_id=CLINIC,
            name="Clínica Norte Renovada",
            tax_id=None,
            timezone=None,
            is_demo=True,
        )
    )

    assert updated.name == "Clínica Norte Renovada"
    assert updated.tax_id == "900000001"
    assert updated.is_demo is True
    [entry] = harness.audit.entries
    assert entry.changed_fields == ("name", "is_demo")


def test_update_of_an_unknown_clinic_is_not_found() -> None:
    harness = Harness(FakeClinics())

    with pytest.raises(ResourceNotFoundError):
        harness.bus.dispatch(
            UpdateClinicCommand(
                actor=platform(),
                clinic_id=UUID(int=999),
                name="Clínica",
                tax_id=None,
                timezone=None,
                is_demo=None,
            )
        )


def test_suspend_records_the_reason_in_the_audit() -> None:
    clinics = FakeClinics(existing())
    harness = Harness(clinics)

    suspended = harness.bus.dispatch(
        SuspendClinicCommand(actor=platform(), clinic_id=CLINIC, reason=REASON)
    )

    assert suspended.status is ClinicStatus.SUSPENDED
    assert suspended.suspended_reason == REASON
    assert suspended.suspended_at == NOW
    [entry] = harness.audit.entries
    assert entry.action == "CLINIC_SUSPENDED"
    assert entry.reason == REASON


@pytest.mark.parametrize("reason", [None, "", "corto", "   "])
def test_suspend_without_a_reason_of_the_allowed_length_is_refused(
    reason: str | None,
) -> None:
    clinics = FakeClinics(existing())
    harness = Harness(clinics)

    with pytest.raises(InsumapError) as refused:
        harness.bus.dispatch(
            SuspendClinicCommand(actor=platform(), clinic_id=CLINIC, reason=reason)
        )

    assert refused.value.code.value == "REASON_REQUIRED"
    assert clinics.rows[CLINIC].status is ClinicStatus.ACTIVE


def test_suspending_a_suspended_clinic_is_an_invalid_transition() -> None:
    harness = Harness(FakeClinics(existing(suspended=True)))

    with pytest.raises(InvalidStateTransitionError):
        harness.bus.dispatch(
            SuspendClinicCommand(actor=platform(), clinic_id=CLINIC, reason=REASON)
        )


def test_reactivate_lifts_the_suspension() -> None:
    clinics = FakeClinics(existing(suspended=True))
    harness = Harness(clinics)

    reactivated = harness.bus.dispatch(
        ReactivateClinicCommand(actor=platform(), clinic_id=CLINIC)
    )

    assert reactivated.status is ClinicStatus.ACTIVE
    assert reactivated.suspended_at is None
    assert reactivated.suspended_reason is None
    assert harness.audit.entries[-1].action == "CLINIC_REACTIVATED"


def test_reactivating_an_active_clinic_is_an_invalid_transition() -> None:
    harness = Harness(FakeClinics(existing()))

    with pytest.raises(InvalidStateTransitionError):
        harness.bus.dispatch(
            ReactivateClinicCommand(actor=platform(), clinic_id=CLINIC)
        )


def test_suspend_requires_clinics_manage() -> None:
    harness = Harness(FakeClinics(existing()))

    with pytest.raises(PermissionDeniedError):
        harness.bus.dispatch(
            SuspendClinicCommand(
                actor=platform(PermissionCode.CLINICS_READ),
                clinic_id=CLINIC,
                reason=REASON,
            )
        )
    assert harness.audit.entries == []
