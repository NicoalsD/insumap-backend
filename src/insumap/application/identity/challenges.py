"""Short-lived single-use challenges (MFA and activation sessions)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import final
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.identity.ports import (
    AuthChallengeRepositoryPort,
    OpaqueTokenPort,
)
from insumap.domain.identity.auth_challenge import AuthChallenge, ChallengePurpose
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class ChallengePolicy:
    """Lifetime and allowed failed attempts of a kind of challenge."""

    ttl: timedelta
    max_attempts: int


@final
class ChallengeService:
    """Issues, finds and saves challenges; the token is returned only once."""

    def __init__(
        self,
        *,
        opaque: OpaqueTokenPort,
        challenges: AuthChallengeRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._opaque = opaque
        self._challenges = challenges
        self._ids = ids
        self._clock = clock

    def issue(
        self,
        *,
        purpose: ChallengePurpose,
        policy: ChallengePolicy,
        user_id: UUID,
        clinic_id: UUID | None,
        invitation_id: UUID | None = None,
    ) -> str:
        """Store a new challenge and return its plain token."""
        issued = self._opaque.new_token()
        self._challenges.add(
            AuthChallenge(
                challenge_id=self._ids.new_id(),
                purpose=purpose,
                token_hash=issued.token_hash,
                user_id=user_id,
                clinic_id=clinic_id,
                invitation_id=invitation_id,
                expires_at=self._clock.now() + policy.ttl,
                max_attempts=policy.max_attempts,
            )
        )
        return issued.plain

    def find_usable(
        self, token: str, *, purpose: ChallengePurpose
    ) -> AuthChallenge | None:
        """The challenge of ``token`` if it is of ``purpose`` and still usable."""
        challenge = self._challenges.find_by_hash(self._opaque.hash(token))
        if challenge is None or not challenge.is_usable(
            purpose=purpose, now=self._clock.now()
        ):
            return None
        return challenge

    def save(self, challenge: AuthChallenge) -> None:
        """Persist attempts and consumption."""
        self._challenges.save(challenge)
