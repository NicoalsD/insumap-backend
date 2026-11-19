"""Access reset of a clinic administrator (P13), behind transaction and audit (P09)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from insumap.application.clinic_admins.commands import (
    ResetClinicAdminAccessCommand,
    ResetClinicAdminAccessCommandHandler,
)
from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import Command, CommandHandler
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.domain.clinic.clinic import Clinic
from insumap.domain.common.errors import ReasonRequiredError, ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.codes import ActivationCode
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.i18n import MessageCatalog
from tests.support.clinic_admin_fakes import FakeClinicAdminProvisioning
from tests.support.clinic_fakes import FakeClinics
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeCodeHasher, FakeUnitOfWorkPort
from tests.support.notifications import InMemoryChannel
from tests.support.users_fakes import FakeActivationCodes

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
PLATFORM = UUID(int=800)
CLINIC = UUID(int=10)
OTHER_CLINIC = UUID(int=11)
MISSING_CLINIC = UUID(int=999)
ADMIN = UUID(int=801)
SUSPENDED_ADMIN = UUID(int=802)
UNKNOWN_ADMIN = UUID(int=900)
REASON = "Revisión de contrato con la clínica"
TTL = timedelta(days=7)
PERMISSIONS = frozenset({PermissionCode.CLINIC_ADMINS_MANAGE})
CODE = "ABCDEFGHJKMNPQRS"


def platform_actor(
    permissions: frozenset[PermissionCode] = PERMISSIONS,
    user_id: UUID = PLATFORM,
) -> Actor:
    """A platform administrator: no clinic in the session."""
    return Actor(
        user_id=user_id,
        clinic_id=None,
        role=Role.PLATFORM_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


def command(
    *,
    user_id: UUID = ADMIN,
    clinic_id: UUID = CLINIC,
    actor: Actor | None = None,
    reason: str | None = REASON,
) -> ResetClinicAdminAccessCommand:
    return ResetClinicAdminAccessCommand(
        actor=actor or platform_actor(),
        clinic_id=clinic_id,
        user_id=user_id,
        reason=reason,
    )


class ClinicAdminAccess:
    """The reset over in-memory doubles, wired as the container does."""

    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.uow = FakeUnitOfWorkPort()
        self.current = CurrentUnitOfWork()
        self.audit = InMemoryAuditLog()
        self.provisioning = FakeClinicAdminProvisioning()
        self.mail = InMemoryChannel()
        self.clinics = FakeClinics(
            Clinic.create(
                clinic_id=CLINIC,
                name="Clínica Norte",
                tax_id="900000001",
                timezone="America/Bogota",
                is_demo=True,
                at=NOW,
            ),
            Clinic.create(
                clinic_id=OTHER_CLINIC,
                name="Clínica Sur",
                tax_id="900000002",
                timezone="America/Bogota",
                is_demo=False,
                at=NOW,
            ),
        )
        self.provisioning.seed(
            user_id=ADMIN,
            clinic_id=CLINIC,
            email="admin.norte@example.test",
            full_name="Ana Administradora",
        )
        self.provisioning.seed(
            user_id=SUSPENDED_ADMIN,
            clinic_id=CLINIC,
            email="suspendido@example.test",
            status="SUSPENDED",
        )
        self.provisioning.seed(
            user_id=UUID(int=803),
            clinic_id=OTHER_CLINIC,
            email="admin.sur@example.test",
        )

    def handler(self) -> ResetClinicAdminAccessCommandHandler:
        return ResetClinicAdminAccessCommandHandler(
            clinics=self.clinics,
            provisioning=self.provisioning,
            codes=FakeActivationCodes(CODE),
            code_hasher=FakeCodeHasher(),
            channel=self.mail,
            messages=MessageCatalog.load_spanish(),
            clock=self.clock,
            current=self.current,
            invitation_ttl=TTL,
        )

    def run(self, handler: CommandHandler[Any, None], cmd: Command[Any]) -> None:
        """Execute like the container: transaction around audit around the handler."""
        guarded = TransactionalCommandHandler(
            AuditingCommandHandler(handler, self.audit, self.clock),
            self.uow,
            self.current,
        )
        guarded.handle(cmd)


def test_resets_the_admin_and_issues_a_hashed_code() -> None:
    world = ClinicAdminAccess()

    world.run(world.handler(), command())

    [reset] = world.provisioning.resets
    assert reset.clinic_id == CLINIC
    assert reset.user_id == ADMIN
    assert reset.code_hash == f"hmac-ACTIVATION-{CODE}"
    assert reset.code_key_id == "key-1"
    assert reset.expires_at == NOW + TTL
    assert world.provisioning.status_of(ADMIN) == "INVITED"
    assert world.uow.commits == 1


def test_sends_the_activation_code_and_the_mfa_notice_after_the_commit() -> None:
    world = ClinicAdminAccess()

    world.run(world.handler(), command())

    activation, mfa_notice = world.mail.delivered
    assert activation.recipient.user_id == ADMIN
    assert activation.recipient.address == "admin.norte@example.test"
    assert ActivationCode(CODE).formatted() in activation.body
    assert mfa_notice.recipient.address == "admin.norte@example.test"
    assert ActivationCode(CODE).formatted() not in mfa_notice.body


def test_the_audit_row_names_the_target_clinic_and_the_reason() -> None:
    world = ClinicAdminAccess()

    world.run(world.handler(), command())

    [entry] = world.audit.entries
    assert entry.clinic_id == CLINIC
    assert entry.action == "CLINIC_ADMIN_ACCESS_RESET"
    assert entry.entity_type == "USER"
    assert entry.entity_id == ADMIN
    assert entry.actor_user_id == PLATFORM
    assert entry.reason == Reason.parse(REASON).text
    assert CODE not in repr(entry)


def test_nobody_resets_his_own_access() -> None:
    world = ClinicAdminAccess()
    actor = platform_actor(user_id=ADMIN)

    with pytest.raises(PermissionDeniedError):
        world.run(world.handler(), command(user_id=ADMIN, actor=actor))

    assert world.provisioning.resets == []
    assert world.mail.delivered == []
    assert world.audit.entries == []


def test_a_missing_permission_is_refused_before_the_clinic_is_looked_up() -> None:
    world = ClinicAdminAccess()
    actor = platform_actor(frozenset({PermissionCode.CLINICS_MANAGE}))

    with pytest.raises(PermissionDeniedError):
        world.run(world.handler(), command(actor=actor, clinic_id=MISSING_CLINIC))

    assert world.provisioning.resets == []


@pytest.mark.parametrize("reason", [None, "", "corto", "x" * 501])
def test_a_reason_outside_the_limits_is_refused_without_writing(
    reason: str | None,
) -> None:
    world = ClinicAdminAccess()

    with pytest.raises(ReasonRequiredError):
        world.run(world.handler(), command(reason=reason))

    assert world.provisioning.resets == []
    assert world.mail.delivered == []


def test_an_unknown_clinic_is_not_found() -> None:
    world = ClinicAdminAccess()

    with pytest.raises(ResourceNotFoundError):
        world.run(world.handler(), command(clinic_id=MISSING_CLINIC))

    assert world.provisioning.resets == []


def test_an_admin_of_another_clinic_is_not_found_and_nothing_is_sent() -> None:
    world = ClinicAdminAccess()

    with pytest.raises(ResourceNotFoundError):
        world.run(world.handler(), command(user_id=UUID(int=803)))

    assert world.provisioning.resets == []
    assert world.mail.delivered == []


def test_an_unknown_admin_is_not_found() -> None:
    world = ClinicAdminAccess()

    with pytest.raises(ResourceNotFoundError):
        world.run(world.handler(), command(user_id=UNKNOWN_ADMIN))

    assert world.provisioning.resets == []


def test_a_suspended_admin_cannot_be_reset_and_nothing_is_sent() -> None:
    world = ClinicAdminAccess()

    with pytest.raises(InvalidStateTransitionError):
        world.run(world.handler(), command(user_id=SUSPENDED_ADMIN))

    assert world.provisioning.resets == []
    assert world.mail.delivered == []
    assert world.audit.entries == []


def test_a_failed_write_leaves_no_audit_row_and_no_email() -> None:
    world = ClinicAdminAccess()
    world.audit.fail = True

    with pytest.raises(RuntimeError):
        world.run(world.handler(), command())

    assert world.mail.delivered == []
