"""Single-use credential invitations (``iam.credential_invitations``).

``PENDING -> VERIFIED -> USED``; also ``EXPIRED``, ``REVOKED`` and ``LOCKED``.
The entity decides without reading the database or the clock: both arrive as
arguments. Every failure is the same ``InvitationInvalidError``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    InvitationInvalidError,
)


class InvitationStatus(StrEnum):
    """Persisted status of an invitation."""

    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    USED = "USED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    LOCKED = "LOCKED"


class InvitationPurpose(StrEnum):
    """What the invitation is for."""

    PATIENT_ACTIVATION = "PATIENT_ACTIVATION"
    STAFF_ACTIVATION = "STAFF_ACTIVATION"
    PASSWORD_RESET = "PASSWORD_RESET"  # noqa: S105 - enum value, not a secret


class InvitationChannel(StrEnum):
    """How the code reaches the holder: printed by the clinic or sent by email."""

    PRINT = "PRINT"
    EMAIL = "EMAIL"


class DeliveryStatus(StrEnum):
    """Result of the email delivery (``iam.credential_invitations.delivery_status``)."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


INVITATION_MACHINE: Final = "credential_invitation"

OPEN_STATUSES: frozenset[InvitationStatus] = frozenset(
    {InvitationStatus.PENDING, InvitationStatus.VERIFIED}
)
"""Statuses that still count as one open invitation per account and purpose."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CredentialInvitation:
    """An invitation found by the keyed hash of its code."""

    invitation_id: UUID
    user_id: UUID
    clinic_id: UUID | None
    patient_id: UUID | None
    purpose: InvitationPurpose
    status: InvitationStatus
    expires_at: datetime
    failed_attempts: int
    verified_at: datetime | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None

    def verify_birth_date(
        self, *, matches: bool, now: datetime, max_attempts: int
    ) -> CredentialInvitation:
        """Step 1 of the activation.

        A pending, unexpired invitation becomes ``VERIFIED`` when the birth date
        matches. A wrong date returns the invitation with one more failed
        attempt (``LOCKED`` at ``max_attempts``) instead of raising, so the
        caller can store it before answering the generic error.
        """
        self._ensure(InvitationStatus.PENDING, now)
        if matches:
            return replace(self, status=InvitationStatus.VERIFIED, verified_at=now)
        attempts = self.failed_attempts + 1
        return replace(
            self,
            failed_attempts=attempts,
            status=(
                InvitationStatus.LOCKED
                if attempts >= max_attempts
                else InvitationStatus.PENDING
            ),
        )

    def verified(self, *, now: datetime) -> CredentialInvitation:
        """Step 1 of a staff activation: possession of the emailed code is enough.

        A pending, unexpired invitation becomes ``VERIFIED`` with no birth date
        (``Seguridad.md``, 3.7).
        """
        self._ensure(InvitationStatus.PENDING, now)
        return replace(self, status=InvitationStatus.VERIFIED, verified_at=now)

    def use(self, *, now: datetime) -> CredentialInvitation:
        """Step 2 of the activation: a verified invitation is consumed."""
        self._ensure(InvitationStatus.VERIFIED, now)
        return replace(self, status=InvitationStatus.USED, used_at=now)

    def revoke(self, *, now: datetime) -> CredentialInvitation:
        """Withdraw an open invitation (``-> REVOKED``), also when it was replaced.

        Only ``PENDING`` and ``VERIFIED`` invitations can be revoked; any other
        status is refused with ``INVALID_STATE_TRANSITION``.
        """
        if self.status not in OPEN_STATUSES:
            raise InvalidStateTransitionError(
                INVITATION_MACHINE, self.status.value, "revoke"
            )
        return replace(self, status=InvitationStatus.REVOKED, revoked_at=now)

    @property
    def is_open(self) -> bool:
        """``True`` while the code can still be used or revoked."""
        return self.status in OPEN_STATUSES

    @property
    def is_locked(self) -> bool:
        """``True`` once too many wrong birth dates were tried."""
        return self.status is InvitationStatus.LOCKED

    def _ensure(self, expected: InvitationStatus, now: datetime) -> None:
        if self.status is not expected or now >= self.expires_at:
            raise InvitationInvalidError
