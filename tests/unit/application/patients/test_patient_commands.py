"""Patient account decisions (P13, P18): transitions, sessions and audit."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Never, cast, override
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import Command, CommandHandler
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.application.patients.commands import (
    DeactivatePatientCommand,
    DeactivatePatientCommandHandler,
    ReactivatePatientCommand,
    ReactivatePatientCommandHandler,
    SuspendPatientCommand,
    SuspendPatientCommandHandler,
)
from insumap.domain.common.errors import ReasonRequiredError, ResourceNotFoundError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import UserAccount
from tests.support.access_fakes import (
    CLINIC,
    PATIENT,
    PATIENT_USER,
    FakeDirectory,
)
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import (
    FakeRefreshTokens,
    FakeUnitOfWorkPort,
    FakeUsers,
)
from tests.support.identity_world import make_account
from tests.support.patient_fakes import FakePatientRoster, FakePendingInvitations
from tests.unit.application.patients.test_patient_queries import (
    ADMIN,
    OTHER_CLINIC,
    PATIENT_OTHER_CLINIC,
    view,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
REASON = "Suspensión por revisión administrativa"
MANAGE = frozenset({PermissionCode.PATIENTS_MANAGE_STATUS})
OTHER_PATIENT_USER = UUID(int=555)


def admin(permissions: frozenset[PermissionCode] = MANAGE) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=CLINIC,
        role=Role.CLINIC_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


class RecordingUsers(FakeUsers):
    """The identity users double, with the list of accounts each save wrote."""

    def __init__(self) -> None:
        super().__init__()
        self.saved: list[UserAccount] = []

    @override
    def save(self, account: UserAccount) -> None:
        self.saved.append(account)
        super().save(account)


class SpyRefreshTokens(FakeRefreshTokens):
    def __init__(self, users: FakeUsers) -> None:
        super().__init__(users)
        self.revoked_for: list[tuple[UUID, RevocationReason]] = []

    @override
    def revoke_all_for_user(
        self, user_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        self.revoked_for.append((user_id, reason))
        super().revoke_all_for_user(user_id, reason=reason, now=now)


def patient_account(
    status: AccountStatus = AccountStatus.ACTIVE, user_id: UUID = PATIENT_USER
) -> UserAccount:
    return make_account(
        user_id,
        None,
        role=Role.PATIENT,
        status=status,
        password=None,
        patient_id=PATIENT,
    )


def roster_of(status: AccountStatus) -> FakePatientRoster:
    return FakePatientRoster(view(PATIENT, status=status))


@dataclass
class World:
    status: AccountStatus = AccountStatus.ACTIVE
    users: RecordingUsers = field(init=False)
    tokens: SpyRefreshTokens = field(init=False)
    invitations: FakePendingInvitations = field(init=False)
    roster: FakePatientRoster = field(init=False)
    audit: InMemoryAuditLog = field(init=False)
    uow: FakeUnitOfWorkPort = field(init=False)

    def __post_init__(self) -> None:
        self.users = RecordingUsers()
        self.users.add(patient_account(self.status))
        self.tokens = SpyRefreshTokens(self.users)
        self.invitations = FakePendingInvitations()
        self.roster = roster_of(self.status)
        self.audit = InMemoryAuditLog()
        self.uow = FakeUnitOfWorkPort()
        self.clock = FixedClock(NOW)
        self.directory = FakeDirectory()
        self.current = CurrentUnitOfWork()

    def guard(
        self, handler: CommandHandler[Command[Never], object]
    ) -> CommandHandler[Command[Never], object]:
        """The order the container uses: transaction around audit around handler."""
        audited = AuditingCommandHandler(handler, self.audit, self.clock)
        return TransactionalCommandHandler(audited, self.uow, self.current)

    def suspend(self) -> SuspendPatientCommandHandler:
        return SuspendPatientCommandHandler(
            patients=self.directory,
            users=self.users,
            refresh_tokens=self.tokens,
            roster=self.roster,
            clock=self.clock,
        )

    def reactivate(self) -> ReactivatePatientCommandHandler:
        return ReactivatePatientCommandHandler(
            patients=self.directory, users=self.users, roster=self.roster
        )

    def deactivate(self) -> DeactivatePatientCommandHandler:
        return DeactivatePatientCommandHandler(
            patients=self.directory,
            users=self.users,
            refresh_tokens=self.tokens,
            invitations=self.invitations,
            roster=self.roster,
            clock=self.clock,
        )


def run[R](handler: CommandHandler[Command[Never], R], command: Command[R]) -> R:
    return cast("R", handler.handle(cast("Command[Never]", command)))


def test_suspend_moves_the_account_revokes_sessions_and_audits() -> None:
    world = World()
    handler = world.suspend()

    result = run(
        handler,
        SuspendPatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
    )

    saved = world.users.saved[-1]
    assert saved.status is AccountStatus.SUSPENDED
    assert saved.status_reason == REASON
    assert saved.token_version == 1
    assert world.tokens.revoked_for == [
        (PATIENT_USER, RevocationReason.ACCOUNT_SUSPENDED)
    ]
    assert result.patient_id == PATIENT


def test_suspend_goes_through_the_audit_decorator_with_the_reason() -> None:
    world = World()
    guarded = world.guard(
        cast("CommandHandler[Command[Never], object]", world.suspend())
    )

    run(
        guarded,
        SuspendPatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
    )

    assert len(world.audit.entries) == 1
    entry = world.audit.entries[0]
    assert entry.action == "PATIENT_SUSPENDED"
    assert entry.entity_type == "PATIENT"
    assert entry.entity_id == PATIENT
    assert entry.reason == REASON
    assert entry.clinic_id == CLINIC


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.IMPORTED,
        AccountStatus.INVITED,
        AccountStatus.SUSPENDED,
        AccountStatus.DEACTIVATED,
    ],
)
def test_suspend_only_leaves_active_accounts(status: AccountStatus) -> None:
    world = World(status=status)

    with pytest.raises(InvalidStateTransitionError):
        run(
            world.suspend(),
            SuspendPatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
        )

    assert world.users.saved == []
    assert world.tokens.revoked_for == []


def test_suspend_requires_a_reason_before_touching_the_account() -> None:
    world = World()

    with pytest.raises(ReasonRequiredError):
        run(
            world.suspend(),
            SuspendPatientCommand(actor=admin(), patient_id=PATIENT, reason="corto"),
        )

    assert world.users.saved == []


def test_suspend_without_the_permission_is_forbidden() -> None:
    world = World()

    with pytest.raises(PermissionDeniedError):
        run(
            world.suspend(),
            SuspendPatientCommand(
                actor=admin(frozenset()), patient_id=PATIENT, reason=REASON
            ),
        )

    assert world.users.saved == []


def test_suspend_of_another_clinic_patient_is_not_found() -> None:
    world = World()
    world.directory.patients[PATIENT_OTHER_CLINIC] = world.directory.patients[PATIENT]
    stranger = Actor(
        user_id=ADMIN,
        clinic_id=OTHER_CLINIC,
        role=Role.CLINIC_ADMIN,
        permissions=MANAGE,
        requires_mfa=True,
        mfa_verified=True,
    )

    with pytest.raises(ResourceNotFoundError):
        run(
            world.suspend(),
            SuspendPatientCommand(
                actor=stranger, patient_id=PATIENT_OTHER_CLINIC, reason=REASON
            ),
        )

    assert world.users.saved == []


def test_suspend_of_a_missing_patient_is_not_found() -> None:
    world = World()

    with pytest.raises(ResourceNotFoundError):
        run(
            world.suspend(),
            SuspendPatientCommand(
                actor=admin(), patient_id=UUID(int=404), reason=REASON
            ),
        )


def test_reactivate_returns_a_suspended_account_to_active() -> None:
    world = World(status=AccountStatus.SUSPENDED)
    world.roster = roster_of(AccountStatus.ACTIVE)

    result = run(
        world.reactivate(),
        ReactivatePatientCommand(actor=admin(), patient_id=PATIENT, reason=None),
    )

    saved = world.users.saved[-1]
    assert saved.status is AccountStatus.ACTIVE
    assert saved.status_reason is None
    assert world.tokens.revoked_for == []
    assert result.account_status is AccountStatus.ACTIVE


def test_reactivate_accepts_a_reason_when_given_and_checks_its_length() -> None:
    world = World(status=AccountStatus.SUSPENDED)

    with pytest.raises(ReasonRequiredError):
        run(
            world.reactivate(),
            ReactivatePatientCommand(actor=admin(), patient_id=PATIENT, reason="x"),
        )
    assert world.users.saved == []


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.IMPORTED,
        AccountStatus.INVITED,
        AccountStatus.ACTIVE,
        AccountStatus.DEACTIVATED,
    ],
)
def test_reactivate_only_leaves_suspended_accounts(status: AccountStatus) -> None:
    world = World(status=status)

    with pytest.raises(InvalidStateTransitionError):
        run(
            world.reactivate(),
            ReactivatePatientCommand(actor=admin(), patient_id=PATIENT, reason=None),
        )

    assert world.users.saved == []


def test_deactivate_closes_the_account_ends_sessions_and_revokes_invitations() -> None:
    world = World()

    run(
        world.deactivate(),
        DeactivatePatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
    )

    saved = world.users.saved[-1]
    assert saved.status is AccountStatus.DEACTIVATED
    assert saved.status_reason == REASON
    assert saved.token_version == 1
    assert world.tokens.revoked_for == [
        (PATIENT_USER, RevocationReason.ACCOUNT_DEACTIVATED)
    ]
    assert world.invitations.revoked == [(PATIENT_USER, ADMIN)]


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.IMPORTED,
        AccountStatus.INVITED,
        AccountStatus.ACTIVE,
        AccountStatus.SUSPENDED,
    ],
)
def test_deactivate_is_allowed_from_every_non_terminal_state(
    status: AccountStatus,
) -> None:
    world = World(status=status)

    result = run(
        world.deactivate(),
        DeactivatePatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
    )

    assert world.users.saved[-1].status is AccountStatus.DEACTIVATED
    assert result.patient_id == PATIENT


def test_deactivated_is_terminal_for_every_command() -> None:
    world = World(status=AccountStatus.DEACTIVATED)

    with pytest.raises(InvalidStateTransitionError):
        run(
            world.deactivate(),
            DeactivatePatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
        )
    with pytest.raises(InvalidStateTransitionError):
        run(
            world.suspend(),
            SuspendPatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
        )
    with pytest.raises(InvalidStateTransitionError):
        run(
            world.reactivate(),
            ReactivatePatientCommand(actor=admin(), patient_id=PATIENT, reason=None),
        )
    assert world.users.saved == []
    assert world.invitations.revoked == []


def test_deactivate_without_the_permission_is_forbidden_and_changes_nothing() -> None:
    world = World()

    with pytest.raises(PermissionDeniedError):
        run(
            world.deactivate(),
            DeactivatePatientCommand(
                actor=admin(frozenset()), patient_id=PATIENT, reason=REASON
            ),
        )

    assert world.users.saved == []
    assert world.invitations.revoked == []


def test_the_patient_account_of_the_directory_is_the_one_changed() -> None:
    world = World()
    world.users.accounts[OTHER_PATIENT_USER] = patient_account(
        user_id=OTHER_PATIENT_USER
    )

    run(
        world.suspend(),
        SuspendPatientCommand(actor=admin(), patient_id=PATIENT, reason=REASON),
    )

    assert world.users.accounts[OTHER_PATIENT_USER].status is AccountStatus.ACTIVE
    assert world.users.accounts[PATIENT_USER].status is AccountStatus.SUSPENDED
