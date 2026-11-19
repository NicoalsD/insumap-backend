"""The first clinic administrator (P13), run behind transaction and audit (P09)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from insumap.application.clinic_admins.commands import (
    CreateClinicAdminCommand,
    CreateClinicAdminCommandHandler,
    CreatedClinicAdmin,
)
from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import Command, CommandHandler
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.domain.clinic.clinic import Clinic
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
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
SUSPENDED_CLINIC = UUID(int=11)
MISSING_CLINIC = UUID(int=999)
EMAIL = "  Admin.Norte@example.test "
FULL_NAME = "Ana Administradora"
TTL = timedelta(days=7)
PERMISSIONS = frozenset({PermissionCode.CLINIC_ADMINS_MANAGE})
CODE = "ABCDEFGHJKMNPQRS"


def platform_actor(
    permissions: frozenset[PermissionCode] = PERMISSIONS,
) -> Actor:
    """A platform administrator: no clinic in the session."""
    return Actor(
        user_id=PLATFORM,
        clinic_id=None,
        role=Role.PLATFORM_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


def command(
    *,
    clinic_id: UUID = CLINIC,
    actor: Actor | None = None,
    email: str = EMAIL,
) -> CreateClinicAdminCommand:
    return CreateClinicAdminCommand(
        actor=actor or platform_actor(),
        clinic_id=clinic_id,
        email=email,
        full_name=FULL_NAME,
    )


class ClinicAdmins:
    """The command over in-memory doubles, wired as the container does."""

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
                clinic_id=SUSPENDED_CLINIC,
                name="Clínica Sur",
                tax_id="900000002",
                timezone="America/Bogota",
                is_demo=False,
                at=NOW,
            ).suspended(reason=Reason.parse("Revisión de contrato"), at=NOW),
        )

    def handler(self) -> CreateClinicAdminCommandHandler:
        return CreateClinicAdminCommandHandler(
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

    def run(
        self, handler: CommandHandler[Any, CreatedClinicAdmin], cmd: Command[Any]
    ) -> CreatedClinicAdmin:
        """Execute like the container: transaction around audit around the handler."""
        guarded = TransactionalCommandHandler(
            AuditingCommandHandler(handler, self.audit, self.clock),
            self.uow,
            self.current,
        )
        return guarded.handle(cmd)


def test_creates_the_admin_of_the_target_clinic_with_the_code_hashed() -> None:
    world = ClinicAdmins()

    created = world.run(world.handler(), command())

    assert created.role is Role.CLINIC_ADMIN
    assert created.email == "Admin.Norte@example.test"
    assert created.invitation_expires_at == NOW + TTL
    [admin] = world.provisioning.created
    assert admin.clinic_id == CLINIC
    assert admin.email == "Admin.Norte@example.test"
    assert admin.full_name == FULL_NAME
    assert admin.code_hash == f"hmac-ACTIVATION-{CODE}"
    assert admin.code_key_id == "key-1"
    assert admin.expires_at == NOW + TTL
    assert world.uow.commits == 1


def test_the_audit_row_names_the_target_clinic_not_the_platform_admin() -> None:
    world = ClinicAdmins()

    created = world.run(world.handler(), command())

    [entry] = world.audit.entries
    assert entry.clinic_id == CLINIC
    assert entry.action == "CLINIC_ADMIN_CREATED"
    assert entry.entity_type == "USER"
    assert entry.entity_id == created.user_id
    assert entry.actor_user_id == PLATFORM
    assert entry.actor_role is Role.PLATFORM_ADMIN
    assert entry.changed_fields == ("email", "full_name", "role")


def test_the_code_leaves_by_email_only_after_the_commit() -> None:
    world = ClinicAdmins()

    created = world.run(world.handler(), command())

    [sent] = world.mail.delivered
    assert sent.recipient.user_id == created.user_id
    assert sent.recipient.address == "Admin.Norte@example.test"
    assert ActivationCode(CODE).formatted() in sent.body


def test_a_missing_permission_is_refused_before_the_clinic_is_looked_up() -> None:
    world = ClinicAdmins()
    actor = platform_actor(frozenset({PermissionCode.CLINICS_MANAGE}))

    with pytest.raises(PermissionDeniedError):
        world.run(world.handler(), command(actor=actor, clinic_id=MISSING_CLINIC))

    assert world.provisioning.created == []
    assert world.mail.delivered == []


def test_an_unknown_clinic_is_not_found() -> None:
    world = ClinicAdmins()

    with pytest.raises(ResourceNotFoundError):
        world.run(world.handler(), command(clinic_id=MISSING_CLINIC))

    assert world.provisioning.created == []


def test_a_clinic_that_is_not_active_refuses_without_writing() -> None:
    world = ClinicAdmins()

    with pytest.raises(InvalidStateTransitionError):
        world.run(world.handler(), command(clinic_id=SUSPENDED_CLINIC))

    assert world.provisioning.created == []
    assert world.mail.delivered == []
    assert world.audit.entries == []


def test_a_repeated_email_is_a_conflict_and_sends_nothing_new() -> None:
    world = ClinicAdmins()
    world.run(world.handler(), command())

    with pytest.raises(ConflictError):
        world.run(world.handler(), command())

    assert len(world.provisioning.created) == 1
    assert len(world.mail.delivered) == 1
    assert len(world.audit.entries) == 1


def test_a_failed_write_leaves_no_audit_row_and_no_email() -> None:
    world = ClinicAdmins()
    world.audit.fail = True

    with pytest.raises(RuntimeError):
        world.run(world.handler(), command())

    assert world.mail.delivered == []
