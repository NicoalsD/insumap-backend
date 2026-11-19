"""Decisions about the staff: create, update, deactivate, unlock and reset MFA (P13).

Each handler checks its permission before any lookup, so a missing permission
is a ``403`` before a missing id is a ``404``. The target must belong to the
caller's clinic and hold a staff role; anything else is a ``404``. Commands run
behind ``TransactionalCommandHandler`` and ``AuditingCommandHandler`` (P09), and
their emails leave only after the commit (``CurrentUnitOfWork.after_commit``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.care_team.ports import CareTeamRepositoryPort
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.ids import IdGenerator
from insumap.application.identity.ports import (
    CodeHasherPort,
    CodePurpose,
    MfaFactorRepositoryPort,
    RefreshTokenRepositoryPort,
    UserRepositoryPort,
)
from insumap.application.notifications.account_notifications import (
    MfaResetNotification,
    StaffActivationNotification,
)
from insumap.application.notifications.notification import (
    NotificationChannel,
    PendingNotification,
    Recipient,
)
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.application.users.access import clinic_of
from insumap.application.users.ports import (
    ActivationCodeGeneratorPort,
    LoginLockoutPort,
    NewStaffInvitation,
    NewStaffMember,
    StaffDirectoryPort,
    StaffInvitationPort,
    StaffMember,
)
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.common.text import invalid_field
from insumap.domain.identity.email import EmailAddress
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import UserAccount
from insumap.domain.staff.profile import ensure_license_for_role, is_staff_role
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock

STAFF_ENTITY: Final = "USER"
EMAIL_TAKEN: Final = "email_taken"
UNSUPPORTED_ROLE_FIELD: Final = "body.role"
UNSUPPORTED: Final = "unsupported"
PROFILE_FIELDS: Final = frozenset({"full_name", "professional_license", "specialty"})


@dataclass(frozen=True, slots=True, kw_only=True)
class CreatedStaff:
    """What ``POST /users`` answers: the new account, never the activation code."""

    user_id: UUID
    email: str
    role: Role
    invitation_expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class DeactivatedStaff:
    """The staff member after closing it, and the patients left without a doctor."""

    member: StaffMember
    patients_pending_reassignment: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateStaffUserCommand(Command[CreatedStaff]):
    """The clinic administrator registers a doctor or another administrator."""

    audit_action: ClassVar[str] = "USER_CREATED"
    audit_entity_type: ClassVar[str] = STAFF_ENTITY

    email: str
    full_name: str
    role: Role
    professional_license: str | None
    specialty: str | None

    @override
    def audit_subject(self, result: CreatedStaff) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.user_id,
            changed_fields=("email", "full_name", "role", "professional_license"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateStaffUserCommand(Command[StaffMember]):
    """Profile fields of a staff member; ``provided`` names the ones the body sent."""

    audit_action: ClassVar[str] = "USER_UPDATED"
    audit_entity_type: ClassVar[str] = STAFF_ENTITY

    user_id: UUID
    full_name: str | None
    professional_license: str | None
    specialty: str | None
    provided: frozenset[str]

    @override
    def audit_subject(self, result: StaffMember) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.user_id,
            changed_fields=tuple(sorted(self.provided & PROFILE_FIELDS)),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DeactivateStaffUserCommand(Command[DeactivatedStaff]):
    """The account is closed for good; its sessions and membership end with it."""

    audit_action: ClassVar[str] = "USER_DEACTIVATED"
    audit_entity_type: ClassVar[str] = STAFF_ENTITY

    user_id: UUID
    reason: str

    @override
    def audit_subject(self, result: DeactivatedStaff) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.member.user_id,
            reason=Reason.parse(self.reason).text,
            changed_fields=("status", "membership", "token_version"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UnlockStaffUserCommand(Command[None]):
    """Lifts the account-wide login lock of a staff member's email."""

    audit_action: ClassVar[str] = "ACCOUNT_UNLOCKED"
    audit_entity_type: ClassVar[str] = STAFF_ENTITY

    user_id: UUID

    @override
    def audit_subject(self, result: None) -> AuditSubject:
        del result
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=self.user_id,
            changed_fields=("login_lockout",),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResetStaffMfaCommand(Command[None]):
    """The second factor is removed; the next sign-in enrolls it again."""

    audit_action: ClassVar[str] = "MFA_RESET"
    audit_entity_type: ClassVar[str] = STAFF_ENTITY

    user_id: UUID
    reason: str

    @override
    def audit_subject(self, result: None) -> AuditSubject:
        del result
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=self.user_id,
            reason=Reason.parse(self.reason).text,
            changed_fields=("mfa_factors", "token_version"),
        )


def _staff_account(
    users: UserRepositoryPort, clinic_id: UUID, user_id: UUID
) -> UserAccount:
    """The account of a staff member of ``clinic_id``; anything else is not found."""
    account = users.get(user_id)
    if (
        account is None
        or account.clinic_id != clinic_id
        or not is_staff_role(account.role)
    ):
        raise ResourceNotFoundError
    return account


@final
class CreateStaffUserCommandHandler(
    CommandHandler[CreateStaffUserCommand, CreatedStaff]
):
    """Creates the account in the caller's clinic and sends its activation code.

    The account starts ``INVITED`` with no password and no MFA. The code is
    stored only as its keyed hash (``CodePurpose.ACTIVATION``) and travels only
    in the email, which leaves after the commit.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        directory: StaffDirectoryPort,
        invitations: StaffInvitationPort,
        codes: ActivationCodeGeneratorPort,
        code_hasher: CodeHasherPort,
        channel: NotificationChannel,
        messages: MessageCatalog,
        ids: IdGenerator,
        clock: Clock,
        current: CurrentUnitOfWork,
        invitation_ttl: timedelta,
    ) -> None:
        self._users = users
        self._directory = directory
        self._invitations = invitations
        self._codes = codes
        self._code_hasher = code_hasher
        self._channel = channel
        self._messages = messages
        self._ids = ids
        self._clock = clock
        self._current = current
        self._ttl = invitation_ttl

    @override
    def handle(self, command: CreateStaffUserCommand) -> CreatedStaff:
        actor = command.actor
        actor.require(PermissionCode.USERS_MANAGE)
        clinic_id = clinic_of(actor)
        if not is_staff_role(command.role):
            raise invalid_field(UNSUPPORTED_ROLE_FIELD, UNSUPPORTED)
        ensure_license_for_role(command.role, command.professional_license)
        email = EmailAddress.from_input(command.email)
        user_id = self._ids.new_id()
        if self._users.email_taken(email.normalized, except_user_id=user_id):
            raise ConflictError(EMAIL_TAKEN)
        now = self._clock.now()
        self._directory.create(
            NewStaffMember(
                user_id=user_id,
                membership_id=self._ids.new_id(),
                clinic_id=clinic_id,
                email=email.original,
                email_normalized=email.normalized,
                full_name=command.full_name,
                role=command.role,
                professional_license=command.professional_license,
                specialty=command.specialty,
            ),
            now=now,
        )
        code = self._codes.generate()
        keyed = self._code_hasher.hash_for_storage(CodePurpose.ACTIVATION, code.value)
        expires_at = now + self._ttl
        self._invitations.add(
            NewStaffInvitation(
                invitation_id=self._ids.new_id(),
                user_id=user_id,
                clinic_id=clinic_id,
                code_hash=keyed.value,
                code_key_id=keyed.key_id,
                expires_at=expires_at,
                issued_by=actor.user_id,
                issued_at=now,
            )
        )
        admin = self._users.get(actor.user_id)
        pending = PendingNotification(
            notification=StaffActivationNotification(
                self._channel,
                self._messages,
                code=code.formatted(),
                days=self._ttl.days,
            ),
            recipient=Recipient(user_id=user_id, address=email.original),
            is_demo=admin is not None
            and admin.clinic is not None
            and admin.clinic.is_demo,
        )
        self._current.after_commit(pending.send)
        return CreatedStaff(
            user_id=user_id,
            email=email.original,
            role=command.role,
            invitation_expires_at=expires_at,
        )


@final
class UpdateStaffUserCommandHandler(
    CommandHandler[UpdateStaffUserCommand, StaffMember]
):
    """Changes the profile fields that were sent; the rest stay as they are.

    Pattern: P13 Command
    """

    def __init__(self, *, directory: StaffDirectoryPort, clock: Clock) -> None:
        self._directory = directory
        self._clock = clock

    @override
    def handle(self, command: UpdateStaffUserCommand) -> StaffMember:
        actor = command.actor
        actor.require(PermissionCode.USERS_MANAGE)
        clinic_id = clinic_of(actor)
        current = self._directory.get(clinic_id, command.user_id)
        if current is None:
            raise ResourceNotFoundError
        provided = command.provided
        full_name = (
            command.full_name
            if "full_name" in provided and command.full_name is not None
            else current.full_name
        )
        license_number = (
            command.professional_license
            if "professional_license" in provided
            else current.professional_license
        )
        specialty = command.specialty if "specialty" in provided else current.specialty
        if "professional_license" in provided:
            ensure_license_for_role(current.role, license_number)
        self._directory.update_profile(
            command.user_id,
            full_name=full_name,
            professional_license=license_number,
            specialty=specialty,
            now=self._clock.now(),
        )
        updated = self._directory.get(clinic_id, command.user_id)
        if updated is None:
            raise ResourceNotFoundError
        return updated


@final
class DeactivateStaffUserCommandHandler(
    CommandHandler[DeactivateStaffUserCommand, DeactivatedStaff]
):
    """Closes the account, revokes every session and ends the membership.

    The patients the doctor cares for keep their open assignments: the count
    tells the administrator who must be reassigned.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        directory: StaffDirectoryPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        care_teams: CareTeamRepositoryPort,
        clock: Clock,
    ) -> None:
        self._users = users
        self._directory = directory
        self._refresh_tokens = refresh_tokens
        self._care_teams = care_teams
        self._clock = clock

    @override
    def handle(self, command: DeactivateStaffUserCommand) -> DeactivatedStaff:
        actor = command.actor
        actor.require(PermissionCode.USERS_MANAGE)
        if command.user_id == actor.user_id:
            raise PermissionDeniedError
        clinic_id = clinic_of(actor)
        reason = Reason.parse(command.reason)
        account = _staff_account(self._users, clinic_id, command.user_id)
        now = self._clock.now()
        self._users.save(
            account.deactivated(reason=reason.text).with_revoked_sessions()
        )
        self._refresh_tokens.revoke_all_for_user(
            account.user_id, reason=RevocationReason.ACCOUNT_DEACTIVATED, now=now
        )
        self._directory.end_membership(account.user_id, reason=reason.text, now=now)
        member = self._directory.get(clinic_id, account.user_id)
        if member is None:
            raise ResourceNotFoundError
        return DeactivatedStaff(
            member=member,
            patients_pending_reassignment=self._care_teams.count_open_for_doctor(
                account.user_id
            ),
        )


@final
class UnlockStaffUserCommandHandler(CommandHandler[UnlockStaffUserCommand, None]):
    """Lifts the global lock of the email (``ACCOUNT`` scope), and says so.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        lockouts: LoginLockoutPort,
        events: SecurityEventPort,
        clock: Clock,
    ) -> None:
        self._users = users
        self._lockouts = lockouts
        self._events = events
        self._clock = clock

    @override
    def handle(self, command: UnlockStaffUserCommand) -> None:
        actor = command.actor
        actor.require(PermissionCode.USERS_MANAGE)
        clinic_id = clinic_of(actor)
        account = _staff_account(self._users, clinic_id, command.user_id)
        if account.email_normalized is not None:
            self._lockouts.clear_account(
                account.email_normalized, now=self._clock.now()
            )
        self._events.record(
            SecurityEvent(
                event_type=SecurityEventType.ACCOUNT_UNLOCKED,
                user_id=account.user_id,
                clinic_id=clinic_id,
            )
        )


@final
class ResetStaffMfaCommandHandler(CommandHandler[ResetStaffMfaCommand, None]):
    """Removes the TOTP factor and the recovery codes, ends every session.

    The holder receives a notice without any code or link. The caller cannot
    reset his own MFA.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        factors: MfaFactorRepositoryPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        events: SecurityEventPort,
        channel: NotificationChannel,
        messages: MessageCatalog,
        current: CurrentUnitOfWork,
        clock: Clock,
    ) -> None:
        self._users = users
        self._factors = factors
        self._refresh_tokens = refresh_tokens
        self._events = events
        self._channel = channel
        self._messages = messages
        self._current = current
        self._clock = clock

    @override
    def handle(self, command: ResetStaffMfaCommand) -> None:
        actor = command.actor
        actor.require(PermissionCode.USERS_MANAGE)
        if command.user_id == actor.user_id:
            raise PermissionDeniedError
        clinic_id = clinic_of(actor)
        Reason.parse(command.reason)
        account = _staff_account(self._users, clinic_id, command.user_id)
        now = self._clock.now()
        totp = self._factors.find_totp(account.user_id)
        if totp is not None:
            self._factors.revoke_totp(totp.factor_id, now=now)
        self._factors.replace_recovery_codes(account.user_id, [], now=now)
        self._users.save(account.with_revoked_sessions())
        self._refresh_tokens.revoke_all_for_user(
            account.user_id, reason=RevocationReason.MFA_RESET, now=now
        )
        self._events.record(
            SecurityEvent(
                event_type=SecurityEventType.MFA_RESET,
                user_id=account.user_id,
                clinic_id=clinic_id,
            )
        )
        if account.email is not None:
            pending = PendingNotification(
                notification=MfaResetNotification(self._channel, self._messages),
                recipient=Recipient(user_id=account.user_id, address=account.email),
                is_demo=account.clinic is not None and account.clinic.is_demo,
            )
            self._current.after_commit(pending.send)
