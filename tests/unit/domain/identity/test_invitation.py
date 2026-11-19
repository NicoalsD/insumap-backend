from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from insumap.domain.identity.errors import InvitationInvalidError
from insumap.domain.identity.invitation import (
    CredentialInvitation,
    InvitationPurpose,
    InvitationStatus,
)
from insumap.shared.errors import ErrorCode

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
MAX_ATTEMPTS = 5


def pending() -> CredentialInvitation:
    return CredentialInvitation(
        invitation_id=UUID(int=1),
        user_id=UUID(int=2),
        clinic_id=UUID(int=3),
        patient_id=UUID(int=4),
        purpose=InvitationPurpose.PATIENT_ACTIVATION,
        status=InvitationStatus.PENDING,
        expires_at=NOW + timedelta(days=7),
        failed_attempts=0,
    )


def test_matching_birth_date_verifies_the_invitation() -> None:
    verified = pending().verify_birth_date(
        matches=True, now=NOW, max_attempts=MAX_ATTEMPTS
    )

    assert verified.status is InvitationStatus.VERIFIED
    assert verified.verified_at == NOW
    assert verified.failed_attempts == 0


def test_wrong_birth_date_counts_an_attempt_without_raising() -> None:
    failed = pending().verify_birth_date(
        matches=False, now=NOW, max_attempts=MAX_ATTEMPTS
    )

    assert failed.status is InvitationStatus.PENDING
    assert failed.failed_attempts == 1


def test_fifth_wrong_birth_date_locks_the_invitation() -> None:
    invitation = pending()
    for _ in range(MAX_ATTEMPTS):
        invitation = invitation.verify_birth_date(
            matches=False, now=NOW, max_attempts=MAX_ATTEMPTS
        )

    assert invitation.is_locked
    with pytest.raises(InvitationInvalidError):
        invitation.verify_birth_date(matches=True, now=NOW, max_attempts=MAX_ATTEMPTS)


@pytest.mark.parametrize(
    "status",
    [
        InvitationStatus.VERIFIED,
        InvitationStatus.USED,
        InvitationStatus.EXPIRED,
        InvitationStatus.REVOKED,
        InvitationStatus.LOCKED,
    ],
)
def test_only_pending_invitations_can_be_verified(status: InvitationStatus) -> None:
    with pytest.raises(InvitationInvalidError) as raised:
        replace(pending(), status=status).verify_birth_date(
            matches=True, now=NOW, max_attempts=MAX_ATTEMPTS
        )

    assert raised.value.code is ErrorCode.INVITATION_INVALID


def test_expired_invitation_is_invalid_even_if_pending() -> None:
    with pytest.raises(InvitationInvalidError):
        pending().verify_birth_date(
            matches=True, now=NOW + timedelta(days=7), max_attempts=MAX_ATTEMPTS
        )


def test_verified_invitation_is_used_once() -> None:
    verified = pending().verify_birth_date(
        matches=True, now=NOW, max_attempts=MAX_ATTEMPTS
    )

    used = verified.use(now=NOW)

    assert used.status is InvitationStatus.USED
    assert used.used_at == NOW
    with pytest.raises(InvitationInvalidError):
        used.use(now=NOW)


def test_pending_invitation_cannot_be_used_without_verification() -> None:
    with pytest.raises(InvitationInvalidError):
        pending().use(now=NOW)
