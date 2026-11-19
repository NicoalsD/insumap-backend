"""Refresh, logout and logout from every device."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn, final

from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWork,
    UnitOfWorkPort,
)
from insumap.application.identity.ports import (
    OpaqueTokenPort,
    RefreshLookup,
    RefreshTokenRepositoryPort,
    UserRepositoryPort,
)
from insumap.application.identity.session import SessionIssuer, SessionTokens
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.errors import (
    ClinicSuspendedError,
    SessionRevokedError,
    UnauthenticatedError,
)
from insumap.domain.identity.refresh_token import RefreshAssessment, RevocationReason
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshSessionInput:
    """The refresh token read from the cookie."""

    refresh_token: str


@final
class RefreshSessionUseCase:
    """Rotates the refresh token and signs a new access token.

    The claim is one atomic update, so two requests can never rotate the same
    token. Presenting a token that was already revoked is reuse: the family is
    revoked, the token version goes up and the event is recorded; that is
    committed before answering ``401 SESSION_REVOKED``.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        opaque: OpaqueTokenPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        users: UserRepositoryPort,
        sessions: SessionIssuer,
        events: SecurityEventPort,
        rate_limit: RateLimitCheck,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._opaque = opaque
        self._refresh_tokens = refresh_tokens
        self._users = users
        self._sessions = sessions
        self._events = events
        self._rate_limit = rate_limit
        self._ids = ids
        self._clock = clock

    def execute(self, input: RefreshSessionInput) -> SessionTokens:
        """Return the new access token and the rotated refresh token."""
        now = self._clock.now()
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            owner = self._refresh_tokens.lookup(self._opaque.hash(input.refresh_token))
            if owner is None:
                raise UnauthenticatedError
            self._rate_limit.ensure(str(owner.user_id))
            uow.apply_context(
                TransactionContext(
                    user_id=owner.user_id, clinic_id=owner.clinic_id, role=owner.role
                )
            )
            claimed = self._refresh_tokens.claim(owner.token_id, now=now)
            if claimed is None:
                self._reject(owner, uow, now)
            if claimed.assess(now) is not RefreshAssessment.VALID:
                raise UnauthenticatedError
            account = self._users.get(claimed.user_id)
            if account is None or not account.can_sign_in:
                raise SessionRevokedError
            if account.clinic_suspended:
                raise ClinicSuspendedError
            issued = self._opaque.new_token()
            successor = claimed.successor(
                token_id=self._ids.new_id(), token_hash=issued.token_hash, now=now
            )
            self._refresh_tokens.add(successor)
            self._refresh_tokens.link_replacement(claimed.token_id, successor.token_id)
            access = self._sessions.access_token(account, session_id=claimed.family_id)
            uow.commit()
        return SessionTokens(
            access_token=access.token,
            access_expires_at=access.expires_at,
            refresh_token=issued.plain,
            refresh_expires_at=successor.expires_at,
        )

    def _reject(self, owner: RefreshLookup, uow: UnitOfWork, now: datetime) -> NoReturn:
        stored = self._refresh_tokens.get(owner.token_id)
        if stored is None or stored.assess(now) is not RefreshAssessment.REUSED:
            raise UnauthenticatedError
        account = self._users.get(stored.user_id)
        if account is not None:
            self._users.save(account.with_revoked_sessions())
        self._refresh_tokens.revoke_family(
            stored.family_id, reason=RevocationReason.REUSE_DETECTED, now=now
        )
        self._events.record(
            SecurityEvent(
                event_type=SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED,
                user_id=stored.user_id,
                clinic_id=stored.clinic_id,
            )
        )
        uow.commit()
        raise SessionRevokedError


@dataclass(frozen=True, slots=True, kw_only=True)
class LogoutInput:
    """The authenticated actor and the refresh token of the cookie, if any."""

    actor: Actor
    refresh_token: str | None


@final
class LogoutUseCase:
    """Revokes the refresh family of this device.

    The family is the one of the cookie when it belongs to the actor, or else
    the ``sid`` of the access token. An enrollment session has neither.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        opaque: OpaqueTokenPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._opaque = opaque
        self._refresh_tokens = refresh_tokens
        self._clock = clock

    def execute(self, input: LogoutInput) -> None:
        """End the session of this device."""
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            family_id = actor.session_id
            if input.refresh_token:
                stored = self._refresh_tokens.find_by_hash(
                    self._opaque.hash(input.refresh_token)
                )
                if stored is not None and stored.user_id == actor.user_id:
                    family_id = stored.family_id
            if family_id is not None:
                self._refresh_tokens.revoke_family(
                    family_id, reason=RevocationReason.LOGOUT, now=self._clock.now()
                )
            uow.commit()


@dataclass(frozen=True, slots=True, kw_only=True)
class LogoutAllInput:
    """The authenticated actor."""

    actor: Actor


@final
class LogoutAllUseCase:
    """Revokes every refresh family and bumps the token version.

    Access tokens still in flight die at their next request, when the token
    version no longer matches.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        users: UserRepositoryPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        events: SecurityEventPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._events = events
        self._clock = clock

    def execute(self, input: LogoutAllInput) -> None:
        """End every session of the account."""
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            account = self._users.get(actor.user_id)
            if account is None:
                raise SessionRevokedError
            self._refresh_tokens.revoke_all_for_user(
                actor.user_id, reason=RevocationReason.LOGOUT_ALL, now=self._clock.now()
            )
            self._users.save(account.with_revoked_sessions())
            self._events.record(
                SecurityEvent(
                    event_type=SecurityEventType.SESSIONS_REVOKED,
                    user_id=actor.user_id,
                    clinic_id=actor.clinic_id,
                )
            )
            uow.commit()
