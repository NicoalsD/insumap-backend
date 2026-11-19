"""Staff commands (P13) and queries, run behind transaction and audit (P09)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import Command, CommandHandler
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.identity.ports import CodePurpose, EncryptedSecret, TotpFactor
from insumap.application.security.events import SecurityEventType
from insumap.application.users.commands import (
    CreateStaffUserCommand,
    CreateStaffUserCommandHandler,
    DeactivateStaffUserCommand,
    DeactivateStaffUserCommandHandler,
    ResetStaffMfaCommand,
    ResetStaffMfaCommandHandler,
    UnlockStaffUserCommand,
    UnlockStaffUserCommandHandler,
    UpdateStaffUserCommand,
    UpdateStaffUserCommandHandler,
)
from insumap.application.users.ports import StaffFilter
from insumap.application.users.queries import (
    GetStaffInput,
    GetStaffUseCase,
    ListStaffInput,
    ListStaffUseCase,
)
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.i18n import MessageCatalog
from tests.support.care_team_fakes import FakeCareTeams
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import (
    FakeCodeHasher,
    FakeFactors,
    FakeIds,
    FakeRefreshTokens,
    FakeSecurityEvents,
    FakeUnitOfWorkPort,
    FakeUsers,
)
from tests.support.identity_world import make_account
from tests.support.notifications import InMemoryChannel
from tests.support.users_fakes import (
    FakeActivationCodes,
    FakeLoginLockouts,
    FakeProfile,
    FakeStaffDirectory,
    FakeStaffInvitations,
)

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
CLINIC_ID = UUID(int=10)
OTHER_CLINIC_ID = UUID(int=20)
ADMIN = UUID(int=11)
DOCTOR = UUID(int=31)
OTHER_DOCTOR = UUID(int=32)
PATIENT = UUID(int=41)
OUTSIDE_DOCTOR = UUID(int=51)
MISSING = UUID(int=999)
FACTOR_ID = UUID(int=70)
ADMIN_PERMISSIONS = frozenset({PermissionCode.USERS_MANAGE, PermissionCode.USERS_READ})
REASON = "Salida de la clínica del personal"
DOCTOR_EMAIL = "doctora@example.test"


def admin_actor(permissions: frozenset[PermissionCode] = ADMIN_PERMISSIONS) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=CLINIC_ID,
        role=Role.CLINIC_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


class SpyRefreshTokens(FakeRefreshTokens):
    """Keeps which account and reason each revocation was for."""

    def __init__(self, users: FakeUsers) -> None:
        super().__init__(users)
        self.revoked_for: list[tuple[UUID, RevocationReason]] = []

    def revoke_all_for_user(
        self, user_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        self.revoked_for.append((user_id, reason))
        super().revoke_all_for_user(user_id, reason=reason, now=now)


class Staff:
    """The staff use cases over in-memory doubles, wired as the container does."""

    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.uow = FakeUnitOfWorkPort()
        self.current = CurrentUnitOfWork()
        self.audit = InMemoryAuditLog()
        self.users = FakeUsers()
        self.factors = FakeFactors()
        self.refresh = SpyRefreshTokens(self.users)
        self.events = FakeSecurityEvents()
        self.lockouts = FakeLoginLockouts()
        self.invitations = FakeStaffInvitations()
        self.directory = FakeStaffDirectory(self.users, self.factors)
        self.care = FakeCareTeams()
        self.mail = InMemoryChannel()
        self.messages = MessageCatalog.load_spanish()
        self.ids = FakeIds()
        self.codes = FakeActivationCodes()
        self.hasher = FakeCodeHasher()
        self.users.add(
            make_account(ADMIN, "admin@example.test", role=Role.CLINIC_ADMIN)
        )
        self.users.add(make_account(DOCTOR, DOCTOR_EMAIL, role=Role.DOCTOR))
        self.users.add(
            make_account(OTHER_DOCTOR, "otro@example.test", role=Role.DOCTOR)
        )
        self.users.add(
            make_account(PATIENT, "paciente@example.test", patient_id=UUID(int=42))
        )
        outside = make_account(OUTSIDE_DOCTOR, "fuera@example.test", role=Role.DOCTOR)
        self.users.add(
            replace(
                outside,
                clinic=ClinicSummary(
                    clinic_id=OTHER_CLINIC_ID,
                    name="Otra Clínica de Prueba",
                    is_demo=True,
                    is_active=True,
                ),
            )
        )
        self.factors.add_totp(
            TotpFactor(
                factor_id=FACTOR_ID,
                user_id=DOCTOR,
                secret=EncryptedSecret(ciphertext=b"sealed", key_id="key-1"),
                last_used_step=None,
                confirmed_at=NOW,
            ),
            now=NOW,
        )

    def run[R](self, handler: CommandHandler[Any, R], command: Command[R]) -> R:
        """Execute like the container: transaction around audit around the handler."""
        guarded = TransactionalCommandHandler(
            AuditingCommandHandler(handler, self.audit, self.clock),
            self.uow,
            self.current,
        )
        return guarded.handle(command)

    def create_handler(self) -> CreateStaffUserCommandHandler:
        return CreateStaffUserCommandHandler(
            users=self.users,
            directory=self.directory,
            invitations=self.invitations,
            codes=self.codes,
            code_hasher=self.hasher,
            channel=self.mail,
            messages=self.messages,
            ids=self.ids,
            clock=self.clock,
            current=self.current,
            invitation_ttl=timedelta(days=7),
        )

    def deactivate_handler(self) -> DeactivateStaffUserCommandHandler:
        return DeactivateStaffUserCommandHandler(
            users=self.users,
            directory=self.directory,
            refresh_tokens=self.refresh,
            care_teams=self.care,
            clock=self.clock,
        )

    def unlock_handler(self) -> UnlockStaffUserCommandHandler:
        return UnlockStaffUserCommandHandler(
            users=self.users,
            lockouts=self.lockouts,
            events=self.events,
            clock=self.clock,
        )

    def reset_mfa_handler(self) -> ResetStaffMfaCommandHandler:
        return ResetStaffMfaCommandHandler(
            users=self.users,
            factors=self.factors,
            refresh_tokens=self.refresh,
            events=self.events,
            channel=self.mail,
            messages=self.messages,
            current=self.current,
            clock=self.clock,
        )


def new_doctor(
    *, email: str = "nueva.medica@example.test", license_number: str | None = "RM-1001"
) -> CreateStaffUserCommand:
    return CreateStaffUserCommand(
        actor=admin_actor(),
        email=email,
        full_name="Nueva Médica de Prueba",
        role=Role.DOCTOR,
        professional_license=license_number,
        specialty="Endocrinología",
    )


def test_creating_a_doctor_stores_an_invited_account_and_emails_the_code() -> None:
    staff = Staff()

    result = staff.run(staff.create_handler(), new_doctor())

    account = staff.users.accounts[result.user_id]
    assert account.status is AccountStatus.INVITED
    assert account.email_normalized == "nueva.medica@example.test"
    assert result.role is Role.DOCTOR
    assert result.invitation_expires_at == NOW + timedelta(days=7)
    [invitation] = staff.invitations.added
    assert invitation.user_id == result.user_id
    assert invitation.clinic_id == CLINIC_ID
    assert (
        invitation.code_hash == f"hmac-{CodePurpose.ACTIVATION.value}-ABCDEFGHJKMNPQRS"
    )
    [delivered] = staff.mail.delivered
    assert delivered.recipient.user_id == result.user_id
    assert "ABCD-EFGH-JKMN-PQRS" in delivered.body
    assert [entry.action for entry in staff.audit.entries] == ["USER_CREATED"]


def test_a_failed_audit_write_sends_no_email() -> None:
    staff = Staff()
    staff.audit.fail = True

    with pytest.raises(RuntimeError):
        staff.run(staff.create_handler(), new_doctor())

    assert staff.mail.delivered == []


def test_a_taken_email_is_a_conflict_and_sends_nothing() -> None:
    staff = Staff()

    with pytest.raises(ConflictError):
        staff.run(staff.create_handler(), new_doctor(email=DOCTOR_EMAIL))

    assert staff.mail.delivered == []
    assert staff.invitations.added == []


def test_a_taken_professional_license_is_a_conflict() -> None:
    staff = Staff()
    staff.directory.profiles[DOCTOR] = FakeProfile(
        clinic_id=CLINIC_ID,
        full_name="Marta Médica",
        professional_license="RM-7",
        specialty=None,
    )

    with pytest.raises(ConflictError) as error:
        staff.run(staff.create_handler(), new_doctor(license_number="RM-7"))

    assert error.value.detail == {"reason": "professional_license_taken"}
    assert staff.mail.delivered == []


def test_a_doctor_without_professional_license_is_refused() -> None:
    staff = Staff()

    with pytest.raises(InsumapError) as error:
        staff.run(staff.create_handler(), new_doctor(license_number=None))

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert staff.directory.created == []


def test_a_clinic_admin_needs_no_professional_license() -> None:
    staff = Staff()
    command = CreateStaffUserCommand(
        actor=admin_actor(),
        email="nueva.admin@example.test",
        full_name="Nuevo Administrador de Prueba",
        role=Role.CLINIC_ADMIN,
        professional_license=None,
        specialty=None,
    )

    result = staff.run(staff.create_handler(), command)

    assert result.role is Role.CLINIC_ADMIN


def test_creating_needs_users_manage_before_anything_else() -> None:
    staff = Staff()
    command = replace(new_doctor(), actor=admin_actor(frozenset()))

    with pytest.raises(PermissionDeniedError):
        staff.run(staff.create_handler(), command)

    assert staff.directory.created == []
    assert staff.audit.entries == []


def test_update_changes_only_the_fields_that_were_sent() -> None:
    staff = Staff()
    staff.directory.profiles[DOCTOR] = FakeProfile(
        clinic_id=CLINIC_ID,
        full_name="Marta Médica",
        professional_license="RM-7",
        specialty=None,
    )
    command = UpdateStaffUserCommand(
        actor=admin_actor(),
        user_id=DOCTOR,
        full_name=None,
        professional_license=None,
        specialty="Endocrinología",
        provided=frozenset({"specialty"}),
    )

    result = staff.run(
        UpdateStaffUserCommandHandler(directory=staff.directory, clock=staff.clock),
        command,
    )

    assert result.full_name == "Marta Médica"
    assert result.professional_license == "RM-7"
    assert result.specialty == "Endocrinología"
    assert [entry.action for entry in staff.audit.entries] == ["USER_UPDATED"]


def test_a_doctor_cannot_lose_the_professional_license() -> None:
    staff = Staff()
    command = UpdateStaffUserCommand(
        actor=admin_actor(),
        user_id=DOCTOR,
        full_name=None,
        professional_license=None,
        specialty=None,
        provided=frozenset({"professional_license"}),
    )

    with pytest.raises(InsumapError) as error:
        staff.run(
            UpdateStaffUserCommandHandler(directory=staff.directory, clock=staff.clock),
            command,
        )

    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_deactivation_closes_the_account_and_revokes_its_sessions() -> None:
    staff = Staff()
    command = DeactivateStaffUserCommand(
        actor=admin_actor(), user_id=DOCTOR, reason=REASON
    )

    result = staff.run(staff.deactivate_handler(), command)

    account = staff.users.accounts[DOCTOR]
    assert account.status is AccountStatus.DEACTIVATED
    assert account.status_reason == REASON
    assert account.token_version == 1
    assert not account.membership_active
    assert (DOCTOR, RevocationReason.ACCOUNT_DEACTIVATED) in staff.refresh.revoked_for
    assert result.member.is_active is False
    assert result.patients_pending_reassignment == 0
    assert [entry.action for entry in staff.audit.entries] == ["USER_DEACTIVATED"]


def test_deactivation_counts_the_patients_left_without_their_doctor() -> None:
    staff = Staff()
    staff.care = FakeCareTeams(
        CareAssignment(
            assignment_id=UUID(int=801),
            clinic_id=CLINIC_ID,
            patient_id=UUID(int=802),
            doctor_user_id=DOCTOR,
            is_primary=True,
            assigned_by=ADMIN,
            assigned_at=NOW,
        )
    )
    command = DeactivateStaffUserCommand(
        actor=admin_actor(), user_id=DOCTOR, reason=REASON
    )

    result = staff.run(staff.deactivate_handler(), command)

    assert result.patients_pending_reassignment == 1


@pytest.mark.parametrize(
    ("user_id", "error"),
    [
        (ADMIN, PermissionDeniedError),
        (PATIENT, ResourceNotFoundError),
        (OUTSIDE_DOCTOR, ResourceNotFoundError),
        (MISSING, ResourceNotFoundError),
    ],
)
def test_deactivation_refuses_self_patients_and_other_clinics(
    user_id: UUID, error: type[InsumapError]
) -> None:
    staff = Staff()
    command = DeactivateStaffUserCommand(
        actor=admin_actor(), user_id=user_id, reason=REASON
    )

    with pytest.raises(error):
        staff.run(staff.deactivate_handler(), command)

    assert staff.refresh.revoked_for == []
    assert staff.audit.entries == []


def test_deactivating_twice_is_a_state_conflict() -> None:
    staff = Staff()
    command = DeactivateStaffUserCommand(
        actor=admin_actor(), user_id=DOCTOR, reason=REASON
    )
    staff.run(staff.deactivate_handler(), command)

    with pytest.raises(InvalidStateTransitionError):
        staff.run(staff.deactivate_handler(), command)


def test_deactivation_needs_a_reason_of_the_allowed_length() -> None:
    staff = Staff()
    command = DeactivateStaffUserCommand(
        actor=admin_actor(), user_id=DOCTOR, reason="corto"
    )

    with pytest.raises(InsumapError) as error:
        staff.run(staff.deactivate_handler(), command)

    assert error.value.code is ErrorCode.REASON_REQUIRED


def test_unlock_lifts_the_account_lock_and_is_recorded() -> None:
    staff = Staff()
    command = UnlockStaffUserCommand(actor=admin_actor(), user_id=DOCTOR)

    staff.run(staff.unlock_handler(), command)

    assert staff.lockouts.cleared == [DOCTOR_EMAIL]
    assert [event.event_type for event in staff.events.events] == [
        SecurityEventType.ACCOUNT_UNLOCKED
    ]
    assert [entry.action for entry in staff.audit.entries] == ["ACCOUNT_UNLOCKED"]


def test_mfa_reset_removes_the_factors_ends_sessions_and_notifies_the_holder() -> None:
    staff = Staff()
    staff.factors.recovery[DOCTOR] = ["code-1", "code-2"]
    command = ResetStaffMfaCommand(actor=admin_actor(), user_id=DOCTOR, reason=REASON)

    staff.run(staff.reset_mfa_handler(), command)

    assert FACTOR_ID in staff.factors.revoked
    assert staff.factors.recovery[DOCTOR] == []
    assert staff.users.accounts[DOCTOR].token_version == 1
    assert (DOCTOR, RevocationReason.MFA_RESET) in staff.refresh.revoked_for
    assert [event.event_type for event in staff.events.events] == [
        SecurityEventType.MFA_RESET
    ]
    [notice] = staff.mail.delivered
    assert notice.recipient.user_id == DOCTOR
    assert "#token=" not in notice.body
    assert [entry.action for entry in staff.audit.entries] == ["MFA_RESET"]


def test_nobody_resets_their_own_mfa() -> None:
    staff = Staff()
    command = ResetStaffMfaCommand(actor=admin_actor(), user_id=ADMIN, reason=REASON)

    with pytest.raises(PermissionDeniedError):
        staff.run(staff.reset_mfa_handler(), command)

    assert staff.factors.revoked == []


def test_listing_returns_the_clinic_staff_filtered_by_role() -> None:
    staff = Staff()
    use_case = ListStaffUseCase(uow=staff.uow, directory=staff.directory)

    page = use_case.execute(
        ListStaffInput(
            actor=admin_actor(),
            filters=StaffFilter(role=Role.DOCTOR),
            page=PageRequest(limit=10),
        )
    )

    assert {member.user_id for member in page.items} == {DOCTOR, OTHER_DOCTOR}
    assert page.next_cursor is None


def test_listing_needs_users_read() -> None:
    staff = Staff()
    use_case = ListStaffUseCase(uow=staff.uow, directory=staff.directory)

    with pytest.raises(PermissionDeniedError):
        use_case.execute(
            ListStaffInput(
                actor=admin_actor(frozenset()),
                filters=StaffFilter(),
                page=PageRequest(limit=10),
            )
        )


def test_get_shows_the_mfa_state_and_hides_other_clinics_and_patients() -> None:
    staff = Staff()
    use_case = GetStaffUseCase(uow=staff.uow, directory=staff.directory)

    member = use_case.execute(GetStaffInput(actor=admin_actor(), user_id=DOCTOR))

    assert member.mfa_enabled is True
    for hidden in (OUTSIDE_DOCTOR, PATIENT, MISSING):
        with pytest.raises(ResourceNotFoundError):
            use_case.execute(GetStaffInput(actor=admin_actor(), user_id=hidden))
