"""Password change of a signed in account (``POST /auth/password/change``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.identity.passwords import NewPasswordService
from insumap.application.identity.ports import (
    ConsentRepositoryPort,
    PasswordHasherPort,
    RefreshTokenRepositoryPort,
    UserRepositoryPort,
)
from insumap.application.identity.session import AuthenticationResult, SessionIssuer
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.errors import (
    ConsentRequiredError,
    InvalidCredentialsError,
    SessionRevokedError,
)
from insumap.domain.identity.password_policy import PersonalData
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangePasswordResult:
    """The new session of this device and the account it belongs to."""

    user_id: UUID
    authentication: AuthenticationResult


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangePasswordCommand(Command[ChangePasswordResult]):
    """The account holder changes the password, proving the current one."""

    audit_action: ClassVar[str] = "PASSWORD_CHANGED"
    audit_entity_type: ClassVar[str] = "USER"

    current_password: str = field(repr=False)
    new_password: str = field(repr=False)

    @override
    def audit_subject(self, result: ChangePasswordResult) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.user_id,
            changed_fields=("password_hash",),
        )


@final
class ChangePasswordCommandHandler(
    CommandHandler[ChangePasswordCommand, ChangePasswordResult]
):
    """Replaces the password, ends every other session and opens a new one.

    ``tv + 1`` kills the access tokens in flight and every refresh family is
    revoked (``PASSWORD_CHANGED``); the device that asked gets a fresh session.
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        hasher: PasswordHasherPort,
        passwords: NewPasswordService,
        refresh_tokens: RefreshTokenRepositoryPort,
        sessions: SessionIssuer,
        consents: ConsentRepositoryPort,
        events: SecurityEventPort,
        rate_limit: RateLimitCheck,
        clock: Clock,
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._passwords = passwords
        self._refresh_tokens = refresh_tokens
        self._sessions = sessions
        self._consents = consents
        self._events = events
        self._rate_limit = rate_limit
        self._clock = clock

    @override
    def handle(self, command: ChangePasswordCommand) -> ChangePasswordResult:
        actor = command.actor
        self._rate_limit.ensure(str(actor.user_id))
        account = self._users.get(actor.user_id)
        if account is None or account.password_hash is None:
            raise SessionRevokedError
        if (
            actor.patient_id is not None
            and actor.clinic_id is not None
            and not self._consents.has_accepted_current(
                actor.patient_id, actor.clinic_id
            )
        ):
            raise ConsentRequiredError
        if not self._hasher.verify(account.password_hash, command.current_password):
            raise InvalidCredentialsError
        local_part = (account.email_normalized or "").partition("@")[0]
        new_hash = self._passwords.accepted_hash(
            account.user_id,
            command.new_password,
            PersonalData(
                email_local_part=local_part, full_name=account.full_name or ""
            ),
        )
        updated = account.with_password_hash(new_hash).with_revoked_sessions()
        self._users.save(updated)
        self._passwords.remember(account.user_id, new_hash)
        self._refresh_tokens.revoke_all_for_user(
            account.user_id,
            reason=RevocationReason.PASSWORD_CHANGED,
            now=self._clock.now(),
        )
        self._events.record(
            SecurityEvent(
                event_type=SecurityEventType.PASSWORD_CHANGED,
                user_id=account.user_id,
                clinic_id=account.clinic_id,
            )
        )
        return ChangePasswordResult(
            user_id=account.user_id,
            authentication=self._sessions.open_full_session(updated),
        )
