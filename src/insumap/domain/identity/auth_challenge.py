"""Short-lived single-use challenges (``iam.auth_challenges``).

The MFA challenge of a login and the activation session are opaque tokens of
256 bits; only their SHA-256 is stored. A challenge expires, allows a limited
number of failed attempts and can be consumed once.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ChallengePurpose(StrEnum):
    """What a challenge token is for."""

    ACTIVATION = "ACTIVATION"
    MFA = "MFA"
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105 - enum value, not a secret
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthChallenge:
    """A stored challenge; it never holds the token itself."""

    challenge_id: UUID
    purpose: ChallengePurpose
    token_hash: str
    user_id: UUID
    clinic_id: UUID | None
    invitation_id: UUID | None
    expires_at: datetime
    max_attempts: int
    attempts: int = 0
    consumed_at: datetime | None = None

    def is_usable(self, *, purpose: ChallengePurpose, now: datetime) -> bool:
        """``True`` if it is of ``purpose``, unexpired, unused and not exhausted."""
        return (
            self.purpose is purpose
            and self.consumed_at is None
            and now < self.expires_at
            and self.attempts < self.max_attempts
        )

    def with_failed_attempt(self) -> AuthChallenge:
        """This challenge with one more failed attempt."""
        return replace(self, attempts=self.attempts + 1)

    def consumed(self, *, now: datetime) -> AuthChallenge:
        """This challenge used up at ``now``."""
        return replace(self, consumed_at=now)
