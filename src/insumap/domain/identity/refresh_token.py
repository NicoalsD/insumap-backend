"""Opaque refresh tokens grouped in families, with rotation and reuse detection.

Each login opens a family (its id travels as ``sid`` in the JWT). Every use of a
refresh token revokes it as ``ROTATED`` and issues its successor in the same
family. Presenting a token that is already revoked means it was stolen or
replayed: the whole family is revoked (``REUSE_DETECTED``) and the session
ends. Only the SHA-256 of a token is ever stored.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class RevocationReason(StrEnum):
    """Why a refresh token stopped being valid (``revoked_reason``)."""

    ROTATED = "ROTATED"
    LOGOUT = "LOGOUT"
    LOGOUT_ALL = "LOGOUT_ALL"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 - enum value, not a secret
    ROLE_CHANGED = "ROLE_CHANGED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    ACCOUNT_DEACTIVATED = "ACCOUNT_DEACTIVATED"
    CLINIC_SUSPENDED = "CLINIC_SUSPENDED"
    MFA_RESET = "MFA_RESET"
    REUSE_DETECTED = "REUSE_DETECTED"
    ADMIN = "ADMIN"


class RefreshAssessment(StrEnum):
    """What presenting a stored refresh token means at a given instant."""

    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshTokenLifetime:
    """Lifetime of each token (inactivity) and of its whole family (absolute)."""

    token: timedelta
    family: timedelta


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshToken:
    """One stored refresh token of a family. It never holds the token itself."""

    token_id: UUID
    user_id: UUID
    clinic_id: UUID | None
    family_id: UUID
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    family_expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: RevocationReason | None = None
    replaced_by_id: UUID | None = None

    @classmethod
    def open_family(  # noqa: PLR0913 - a family needs every key of its first row
        cls,
        *,
        token_id: UUID,
        family_id: UUID,
        user_id: UUID,
        clinic_id: UUID | None,
        token_hash: str,
        now: datetime,
        lifetime: RefreshTokenLifetime,
    ) -> RefreshToken:
        """First token of a new family, issued at login."""
        family_expires_at = now + lifetime.family
        return cls(
            token_id=token_id,
            user_id=user_id,
            clinic_id=clinic_id,
            family_id=family_id,
            token_hash=token_hash,
            issued_at=now,
            expires_at=min(now + lifetime.token, family_expires_at),
            family_expires_at=family_expires_at,
        )

    @property
    def is_revoked(self) -> bool:
        """``True`` once the token was rotated or revoked for any reason."""
        return self.revoked_at is not None

    def assess(self, now: datetime) -> RefreshAssessment:
        """Classify a presentation of this token at ``now``.

        A revoked token is reuse even if it also expired: a replay of an old
        token must still end the family.
        """
        if self.is_revoked:
            return RefreshAssessment.REUSED
        if now >= self.expires_at or now >= self.family_expires_at:
            return RefreshAssessment.EXPIRED
        return RefreshAssessment.VALID

    def successor(
        self, *, token_id: UUID, token_hash: str, now: datetime
    ) -> RefreshToken:
        """The token that replaces this one when it rotates.

        It lives as long as this one did, but never past the end of the family.
        """
        lifetime = self.expires_at - self.issued_at
        return RefreshToken(
            token_id=token_id,
            user_id=self.user_id,
            clinic_id=self.clinic_id,
            family_id=self.family_id,
            token_hash=token_hash,
            issued_at=now,
            expires_at=min(now + lifetime, self.family_expires_at),
            family_expires_at=self.family_expires_at,
        )

    def revoked(self, *, reason: RevocationReason, now: datetime) -> RefreshToken:
        """This token revoked for ``reason``; an already revoked one is kept."""
        if self.is_revoked:
            return self
        return replace(self, revoked_at=now, revoked_reason=reason)
