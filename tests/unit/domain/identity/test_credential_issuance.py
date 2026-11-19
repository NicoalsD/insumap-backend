"""Credential invitations and the patient account states they move (P18).

Pure domain tests: no database, no FastAPI, no clock (the instants are fixed).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.identity.invitation import (
    CredentialInvitation,
    InvitationPurpose,
    InvitationStatus,
)
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary, UserAccount
from insumap.shared.errors import ErrorCode

NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)


def invitation(status: InvitationStatus) -> CredentialInvitation:
    return CredentialInvitation(
        invitation_id=UUID(int=1),
        user_id=UUID(int=2),
        clinic_id=UUID(int=3),
        patient_id=UUID(int=4),
        purpose=InvitationPurpose.PATIENT_ACTIVATION,
        status=status,
        expires_at=NOW + timedelta(days=7),
        failed_attempts=0,
    )


@pytest.mark.parametrize(
    "status", [InvitationStatus.PENDING, InvitationStatus.VERIFIED]
)
def test_an_open_invitation_can_be_revoked(status: InvitationStatus) -> None:
    revoked = invitation(status).revoke(now=LATER)

    assert revoked.status is InvitationStatus.REVOKED
    assert revoked.revoked_at == LATER
    assert not revoked.is_open


@pytest.mark.parametrize(
    "status",
    [
        InvitationStatus.USED,
        InvitationStatus.EXPIRED,
        InvitationStatus.REVOKED,
        InvitationStatus.LOCKED,
    ],
)
def test_a_closed_invitation_cannot_be_revoked(status: InvitationStatus) -> None:
    with pytest.raises(InvalidStateTransitionError) as refused:
        invitation(status).revoke(now=LATER)

    assert refused.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert refused.value.detail == {
        "machine": "credential_invitation",
        "status": status.value,
        "action": "revoke",
    }


def test_open_means_pending_or_verified() -> None:
    assert invitation(InvitationStatus.PENDING).is_open
    assert invitation(InvitationStatus.VERIFIED).is_open
    assert not invitation(InvitationStatus.USED).is_open


def account(status: AccountStatus) -> UserAccount:
    return UserAccount(
        user_id=UUID(int=2),
        email=None,
        email_normalized=None,
        full_name="Paciente de Prueba",
        password_hash=None,
        status=status,
        token_version=0,
        role=Role.PATIENT,
        requires_mfa=False,
        membership_active=True,
        clinic=ClinicSummary(
            clinic_id=UUID(int=3), name="Clínica Demo", is_demo=True, is_active=True
        ),
        patient_id=UUID(int=4),
    )


def test_issuing_moves_an_imported_account_to_invited() -> None:
    assert account(AccountStatus.IMPORTED).invited().status is AccountStatus.INVITED


def test_reissuing_keeps_an_invited_account_invited() -> None:
    assert account(AccountStatus.INVITED).invited().status is AccountStatus.INVITED


@pytest.mark.parametrize(
    "status",
    [AccountStatus.ACTIVE, AccountStatus.SUSPENDED, AccountStatus.DEACTIVATED],
)
def test_issuing_is_refused_once_the_account_is_past_activation(
    status: AccountStatus,
) -> None:
    with pytest.raises(InvalidStateTransitionError):
        account(status).invited()


def test_revoking_returns_an_invited_account_to_imported() -> None:
    reverted = account(AccountStatus.INVITED).reverted_to_imported()

    assert reverted.status is AccountStatus.IMPORTED


def test_revoking_is_refused_for_an_account_that_was_never_invited() -> None:
    with pytest.raises(InvalidStateTransitionError):
        account(AccountStatus.IMPORTED).reverted_to_imported()


def test_other_fields_of_the_account_are_kept() -> None:
    before = replace(account(AccountStatus.IMPORTED), token_version=3)

    after = before.invited()

    assert after.token_version == 3
    assert after.patient_id == before.patient_id
