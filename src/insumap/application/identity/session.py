"""Issues the tokens of a session once the user proved who they are."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.identity.ports import (
    AccessGrant,
    IssuedAccessToken,
    OpaqueTokenPort,
    RefreshTokenRepositoryPort,
    TokenIssuerPort,
)
from insumap.domain.identity.refresh_token import RefreshToken, RefreshTokenLifetime
from insumap.domain.identity.session import AuthenticationMethod, LoginStatus
from insumap.domain.identity.user import UserAccount
from insumap.shared.time import Clock

PASSWORD_ONLY = (AuthenticationMethod.PASSWORD.value,)
PASSWORD_AND_OTP = (
    AuthenticationMethod.PASSWORD.value,
    AuthenticationMethod.ONE_TIME_PASSWORD.value,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionLifetimes:
    """Refresh lifetimes of patients and of staff (who must use MFA)."""

    patient: RefreshTokenLifetime
    staff: RefreshTokenLifetime

    def for_account(self, account: UserAccount) -> RefreshTokenLifetime:
        """Staff sessions last one shift; patient sessions last longer."""
        return self.staff if account.requires_mfa else self.patient


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionTokens:
    """Tokens handed to the client. The refresh goes only into the cookie."""

    access_token: str
    access_expires_at: datetime
    refresh_token: str | None = None
    refresh_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticationResult:
    """Outcome of a login, MFA step or activation (API.md, section 2.3)."""

    status: LoginStatus
    session: SessionTokens | None = None
    challenge_token: str | None = None


def amr_for(account: UserAccount) -> tuple[str, ...]:
    """Methods behind a full session of ``account``."""
    return PASSWORD_AND_OTP if account.requires_mfa else PASSWORD_ONLY


@final
class SessionIssuer:
    """Opens refresh token families and signs access tokens."""

    def __init__(
        self,
        *,
        tokens: TokenIssuerPort,
        opaque: OpaqueTokenPort,
        refresh_tokens: RefreshTokenRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
        lifetimes: SessionLifetimes,
    ) -> None:
        self._tokens = tokens
        self._opaque = opaque
        self._refresh_tokens = refresh_tokens
        self._ids = ids
        self._clock = clock
        self._lifetimes = lifetimes

    def open_full_session(self, account: UserAccount) -> AuthenticationResult:
        """New refresh family plus an access token with every method used."""
        issued = self._opaque.new_token()
        token = RefreshToken.open_family(
            token_id=self._ids.new_id(),
            family_id=self._ids.new_id(),
            user_id=account.user_id,
            clinic_id=account.clinic_id,
            token_hash=issued.token_hash,
            now=self._clock.now(),
            lifetime=self._lifetimes.for_account(account),
        )
        self._refresh_tokens.add(token)
        access = self.access_token(account, session_id=token.family_id)
        return AuthenticationResult(
            status=LoginStatus.AUTHENTICATED,
            session=SessionTokens(
                access_token=access.token,
                access_expires_at=access.expires_at,
                refresh_token=issued.plain,
                refresh_expires_at=token.expires_at,
            ),
        )

    def enrollment_session(self, account: UserAccount) -> AuthenticationResult:
        """Access token with ``amr: ["pwd"]`` and no refresh: MFA must be set up."""
        access = self._tokens.issue(
            AccessGrant(
                user_id=account.user_id,
                role=account.role,
                clinic_id=account.clinic_id,
                token_version=account.token_version,
                session_id=None,
                amr=PASSWORD_ONLY,
            )
        )
        return AuthenticationResult(
            status=LoginStatus.MFA_ENROLLMENT_REQUIRED,
            session=SessionTokens(
                access_token=access.token, access_expires_at=access.expires_at
            ),
        )

    def access_token(
        self, account: UserAccount, *, session_id: UUID
    ) -> IssuedAccessToken:
        """Access token of a full session of ``account`` in family ``session_id``."""
        return self._tokens.issue(
            AccessGrant(
                user_id=account.user_id,
                role=account.role,
                clinic_id=account.clinic_id,
                token_version=account.token_version,
                session_id=session_id,
                amr=amr_for(account),
            )
        )
