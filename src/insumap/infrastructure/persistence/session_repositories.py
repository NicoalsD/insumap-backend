"""Refresh token families and MFA challenges."""

from __future__ import annotations

from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import ColumnElement, Select, select, text, update

from insumap.application.identity.ports import (
    AuthChallengeRepositoryPort,
    RefreshLookup,
    RefreshTokenRepositoryPort,
)
from insumap.domain.identity.auth_challenge import AuthChallenge, ChallengePurpose
from insumap.domain.identity.refresh_token import RefreshToken, RevocationReason
from insumap.domain.identity.roles import Role
from insumap.infrastructure.persistence.orm import AuthChallengeOrm, RefreshTokenOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

REFRESH_LOOKUP = text("SELECT * FROM iam.lookup_refresh_token(:token_hash)")


def _token(row: RefreshTokenOrm) -> RefreshToken:
    return RefreshToken(
        token_id=row.id,
        user_id=row.user_id,
        clinic_id=row.clinic_id,
        family_id=row.family_id,
        token_hash=row.token_hash,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        family_expires_at=row.family_expires_at,
        revoked_at=row.revoked_at,
        revoked_reason=(
            None if row.revoked_reason is None else RevocationReason(row.revoked_reason)
        ),
        replaced_by_id=row.replaced_by_id,
    )


@final
class RefreshTokenRepository(RefreshTokenRepositoryPort):
    """``iam.refresh_tokens``: only the SHA-256 of each token is stored."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, token: RefreshToken) -> None:
        self._current.get().add(
            RefreshTokenOrm(
                id=token.token_id,
                user_id=token.user_id,
                clinic_id=token.clinic_id,
                family_id=token.family_id,
                token_hash=token.token_hash,
                issued_at=token.issued_at,
                expires_at=token.expires_at,
                family_expires_at=token.family_expires_at,
            )
        )
        self._current.get().flush()

    @override
    def lookup(self, token_hash: str) -> RefreshLookup | None:
        row = (
            self._current.get()
            .execute(REFRESH_LOOKUP, {"token_hash": token_hash})
            .mappings()
            .first()
        )
        if row is None:
            return None
        role = row["role"]
        return RefreshLookup(
            token_id=row["token_id"],
            user_id=row["user_id"],
            clinic_id=row["clinic_id"],
            role=None if role is None else Role(role),
        )

    @override
    def claim(self, token_id: UUID, *, now: datetime) -> RefreshToken | None:
        statement = (
            update(RefreshTokenOrm)
            .where(RefreshTokenOrm.id == token_id, RefreshTokenOrm.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=RevocationReason.ROTATED.value)
            .returning(
                RefreshTokenOrm.id,
                RefreshTokenOrm.user_id,
                RefreshTokenOrm.clinic_id,
                RefreshTokenOrm.family_id,
                RefreshTokenOrm.token_hash,
                RefreshTokenOrm.issued_at,
                RefreshTokenOrm.expires_at,
                RefreshTokenOrm.family_expires_at,
            )
            .execution_options(synchronize_session=False)
        )
        row = self._current.get().execute(statement).first()
        if row is None:
            return None
        return RefreshToken(
            token_id=row.id,
            user_id=row.user_id,
            clinic_id=row.clinic_id,
            family_id=row.family_id,
            token_hash=row.token_hash,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
            family_expires_at=row.family_expires_at,
        )

    @override
    def get(self, token_id: UUID) -> RefreshToken | None:
        return self._first(
            select(RefreshTokenOrm).where(RefreshTokenOrm.id == token_id)
        )

    @override
    def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        return self._first(
            select(RefreshTokenOrm).where(RefreshTokenOrm.token_hash == token_hash)
        )

    def _first(self, statement: Select[RefreshTokenOrm]) -> RefreshToken | None:
        row = self._current.get().scalars(statement).first()
        return None if row is None else _token(row)

    @override
    def link_replacement(self, token_id: UUID, replaced_by_id: UUID) -> None:
        self._current.get().execute(
            update(RefreshTokenOrm)
            .where(RefreshTokenOrm.id == token_id)
            .values(replaced_by_id=replaced_by_id)
        )

    @override
    def revoke_family(
        self, family_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        self._revoke(RefreshTokenOrm.family_id == family_id, reason, now)

    @override
    def revoke_all_for_user(
        self, user_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        self._revoke(RefreshTokenOrm.user_id == user_id, reason, now)

    def _revoke(
        self, condition: ColumnElement[bool], reason: RevocationReason, now: datetime
    ) -> None:
        self._current.get().execute(
            update(RefreshTokenOrm)
            .where(condition, RefreshTokenOrm.revoked_at.is_(None))
            .values(revoked_at=now, revoked_reason=reason.value)
        )


@final
class AuthChallengeRepository(AuthChallengeRepositoryPort):
    """``iam.auth_challenges`` (no RLS: found by a 256 bit token hash)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, challenge: AuthChallenge) -> None:
        self._current.get().add(
            AuthChallengeOrm(
                id=challenge.challenge_id,
                purpose=challenge.purpose.value,
                token_hash=challenge.token_hash,
                user_id=challenge.user_id,
                clinic_id=challenge.clinic_id,
                invitation_id=challenge.invitation_id,
                attempts=challenge.attempts,
                max_attempts=challenge.max_attempts,
                expires_at=challenge.expires_at,
            )
        )
        self._current.get().flush()

    @override
    def find_by_hash(self, token_hash: str) -> AuthChallenge | None:
        row = (
            self._current.get()
            .scalars(
                select(AuthChallengeOrm).where(
                    AuthChallengeOrm.token_hash == token_hash
                )
            )
            .first()
        )
        if row is None:
            return None
        return AuthChallenge(
            challenge_id=row.id,
            purpose=ChallengePurpose(row.purpose),
            token_hash=row.token_hash,
            user_id=row.user_id,
            clinic_id=row.clinic_id,
            invitation_id=row.invitation_id,
            expires_at=row.expires_at,
            max_attempts=row.max_attempts,
            attempts=row.attempts,
            consumed_at=row.consumed_at,
        )

    @override
    def save(self, challenge: AuthChallenge) -> None:
        self._current.get().execute(
            update(AuthChallengeOrm)
            .where(AuthChallengeOrm.id == challenge.challenge_id)
            .values(attempts=challenge.attempts, consumed_at=challenge.consumed_at)
        )
