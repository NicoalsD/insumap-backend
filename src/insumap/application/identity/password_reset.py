"""Forgotten password: request the emailed link, then choose a new password."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import final

from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.challenges import ChallengePolicy, ChallengeService
from insumap.application.identity.email_verification import link_with_token
from insumap.application.identity.passwords import NewPasswordService
from insumap.application.identity.ports import (
    RefreshTokenRepositoryPort,
    UserRepositoryPort,
)
from insumap.application.notifications.account_notifications import (
    PasswordChangedNotification,
    PasswordResetNotification,
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
from insumap.application.security.rate_limit import (
    RateLimitCheck,
    RateLimiterPort,
    RateLimitRule,
)
from insumap.domain.identity.auth_challenge import ChallengePurpose
from insumap.domain.identity.email import EmailAddress
from insumap.domain.identity.errors import InvitationInvalidError
from insumap.domain.identity.password_policy import PersonalData
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.domain.identity.user import UserAccount
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock

SECONDS_PER_MINUTE = 60


@dataclass(frozen=True, slots=True, kw_only=True)
class PasswordResetPolicy:
    """Lifetime of the link and where it points (``<base>/<path>#token=...``)."""

    ttl: timedelta
    max_attempts: int
    link_base_url: str
    link_path: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestPasswordResetInput:
    """The email typed in the form and the address of the caller."""

    email: str
    client_ip: str


@final
class RequestPasswordResetUseCase:
    """Emails a reset link when the account exists, is active and has a verified email.

    The answer never depends on the account: a missing, inactive or unverified
    account, and a request over the limits, all end quietly like a success. The
    limits per IP and per email are counted without ever raising.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        users: UserRepositoryPort,
        challenges: ChallengeService,
        events: SecurityEventPort,
        limiter: RateLimiterPort,
        ip_rule: RateLimitRule,
        email_rule: RateLimitRule,
        policy: PasswordResetPolicy,
        channel: NotificationChannel,
        messages: MessageCatalog,
    ) -> None:
        self._uow = uow
        self._users = users
        self._challenges = challenges
        self._events = events
        self._limiter = limiter
        self._ip_rule = ip_rule
        self._email_rule = email_rule
        self._policy = policy
        self._channel = channel
        self._messages = messages

    def execute(self, input: RequestPasswordResetInput) -> None:
        """Send the link if the request qualifies; always return normally."""
        email = EmailAddress.from_input(input.email)
        if not self._within_limits(input.client_ip, email):
            return
        pending = self._prepare(email)
        if pending is not None:
            pending.send()

    def _within_limits(self, client_ip: str, email: EmailAddress) -> bool:
        by_ip = self._limiter.hit(self._ip_rule, client_ip).allowed
        digest = hashlib.sha256(email.normalized.encode()).hexdigest()
        by_email = self._limiter.hit(self._email_rule, digest).allowed
        return by_ip and by_email

    def _prepare(self, email: EmailAddress) -> PendingNotification | None:
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            identity = self._users.find_login_identity(email.normalized)
            if identity is None or not identity.can_sign_in:
                return None
            uow.apply_context(
                TransactionContext(
                    user_id=identity.user_id,
                    clinic_id=identity.clinic_id,
                    role=identity.role,
                )
            )
            account = self._users.get(identity.user_id)
            if (
                account is None
                or not account.can_sign_in
                or account.clinic_suspended
                or not account.email_verified
                or account.email is None
            ):
                return None
            token = self._challenges.issue(
                purpose=ChallengePurpose.PASSWORD_RESET,
                policy=ChallengePolicy(
                    ttl=self._policy.ttl, max_attempts=self._policy.max_attempts
                ),
                user_id=account.user_id,
                clinic_id=account.clinic_id,
            )
            self._events.record(
                SecurityEvent(
                    event_type=SecurityEventType.PASSWORD_RESET_REQUESTED,
                    user_id=account.user_id,
                    clinic_id=account.clinic_id,
                )
            )
            uow.commit()
        return PendingNotification(
            notification=PasswordResetNotification(
                self._channel,
                self._messages,
                link=link_with_token(
                    self._policy.link_base_url, self._policy.link_path, token
                ),
                minutes=int(self._policy.ttl.total_seconds() // SECONDS_PER_MINUTE),
            ),
            recipient=Recipient(user_id=account.user_id, address=account.email),
            is_demo=account.clinic is not None and account.clinic.is_demo,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletePasswordResetInput:
    """The token of the emailed link and the chosen password."""

    token: str
    new_password: str
    client_ip: str


@final
class CompletePasswordResetUseCase:
    """Sets the new password, ends every session and tells the holder.

    A password that breaks the policy fails with ``422`` and leaves the token
    usable. Any other failure of the token is the single ``410``.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        challenges: ChallengeService,
        users: UserRepositoryPort,
        passwords: NewPasswordService,
        refresh_tokens: RefreshTokenRepositoryPort,
        events: SecurityEventPort,
        rate_limit: RateLimitCheck,
        channel: NotificationChannel,
        messages: MessageCatalog,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._challenges = challenges
        self._users = users
        self._passwords = passwords
        self._refresh_tokens = refresh_tokens
        self._events = events
        self._rate_limit = rate_limit
        self._channel = channel
        self._messages = messages
        self._clock = clock

    def execute(self, input: CompletePasswordResetInput) -> None:
        """Consume the token and replace the password."""
        self._rate_limit.ensure(input.client_ip)
        now = self._clock.now()
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            challenge = self._challenges.find_usable(
                input.token, purpose=ChallengePurpose.PASSWORD_RESET
            )
            if challenge is None:
                raise InvitationInvalidError
            uow.apply_context(
                TransactionContext(
                    user_id=challenge.user_id, clinic_id=challenge.clinic_id
                )
            )
            account = self._users.get(challenge.user_id)
            if account is None or not account.can_sign_in or account.clinic_suspended:
                raise InvitationInvalidError
            local_part = (account.email_normalized or "").partition("@")[0]
            new_hash = self._passwords.accepted_hash(
                account.user_id,
                input.new_password,
                PersonalData(
                    email_local_part=local_part, full_name=account.full_name or ""
                ),
            )
            self._users.save(
                account.with_password_hash(new_hash).with_revoked_sessions()
            )
            self._passwords.remember(account.user_id, new_hash)
            self._challenges.save(challenge.consumed(now=now))
            self._refresh_tokens.revoke_all_for_user(
                account.user_id, reason=RevocationReason.PASSWORD_CHANGED, now=now
            )
            self._events.record(
                SecurityEvent(
                    event_type=SecurityEventType.PASSWORD_CHANGED,
                    user_id=account.user_id,
                    clinic_id=account.clinic_id,
                )
            )
            uow.commit()
        self._notify_holder(account)

    def _notify_holder(self, account: UserAccount) -> None:
        if not account.email_verified or account.email is None:
            return
        PendingNotification(
            notification=PasswordChangedNotification(self._channel, self._messages),
            recipient=Recipient(user_id=account.user_id, address=account.email),
            is_demo=account.clinic is not None and account.clinic.is_demo,
        ).send()
