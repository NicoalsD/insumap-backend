"""Acceptance and storage of a new password (activation, change, reset)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.identity.ports import PasswordHasherPort, PasswordHistoryPort
from insumap.domain.identity.password_policy import PasswordPolicy, PersonalData
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class PasswordRules:
    """The password policy and how many past passwords may not be reused."""

    policy: PasswordPolicy
    history_size: int


@final
class NewPasswordService:
    """Checks a new password against the policy and the history, then hashes it."""

    def __init__(
        self,
        *,
        rules: PasswordRules,
        hasher: PasswordHasherPort,
        history: PasswordHistoryPort,
        clock: Clock,
    ) -> None:
        self._rules = rules
        self._hasher = hasher
        self._history = history
        self._clock = clock

    def accepted_hash(self, user_id: UUID, plain: str, personal: PersonalData) -> str:
        """Return the hash of ``plain`` or raise ``PasswordPolicyError``."""
        recent = self._history.recent_hashes(user_id, limit=self._rules.history_size)
        reused = any(self._hasher.verify(stored, plain) for stored in recent)
        self._rules.policy.ensure_acceptable(plain, personal, reused=reused)
        return self._hasher.hash(plain)

    def remember(self, user_id: UUID, password_hash: str) -> None:
        """Add the hash now in use to the history."""
        self._history.add(user_id, password_hash, now=self._clock.now())
