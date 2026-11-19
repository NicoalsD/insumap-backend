from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.auth_challenge import AuthChallenge, ChallengePurpose
from insumap.domain.identity.email import EmailAddress
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary, UserAccount

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
CLINIC = ClinicSummary(
    clinic_id=UUID(int=3), name="Clínica de Prueba Demo", is_demo=True, is_active=True
)


def patient(status: AccountStatus = AccountStatus.ACTIVE) -> UserAccount:
    return UserAccount(
        user_id=UUID(int=1),
        email=None,
        email_normalized=None,
        full_name="Paciente de Prueba Uno",
        password_hash=None,
        status=status,
        token_version=0,
        role=Role.PATIENT,
        requires_mfa=False,
        membership_active=True,
        clinic=CLINIC,
        patient_id=UUID(int=4),
    )


def test_email_is_normalized_with_nfkc_trim_and_lower_case() -> None:
    email = EmailAddress.from_input("  Paciente.Uno@EXAMPLE.test ")

    assert email.original == "Paciente.Uno@EXAMPLE.test"
    assert email.normalized == "paciente.uno@example.test"
    assert email.local_part == "paciente.uno"


def test_only_active_account_with_active_membership_signs_in() -> None:
    assert patient().can_sign_in
    assert not patient(AccountStatus.SUSPENDED).can_sign_in
    assert not replace(patient(), membership_active=False).can_sign_in


def test_suspended_clinic_is_reported() -> None:
    suspended = replace(patient(), clinic=replace(CLINIC, is_active=False))

    assert suspended.clinic_suspended
    assert not patient().clinic_suspended
    assert replace(patient(), clinic=None).clinic_id is None


def test_revoking_sessions_increments_the_token_version() -> None:
    account = patient().with_revoked_sessions()

    assert account.token_version == 1
    assert account.with_password_hash("hash").password_hash == "hash"


def test_activation_moves_an_invited_account_to_active() -> None:
    email = EmailAddress.from_input("paciente.uno@example.test")

    active = patient(AccountStatus.INVITED).activated(password_hash="h", email=email)

    assert active.status is AccountStatus.ACTIVE
    assert active.email_normalized == "paciente.uno@example.test"
    assert active.password_hash == "h"


def test_activation_of_an_active_account_is_refused() -> None:
    with pytest.raises(InvalidStateTransitionError):
        patient().activated(
            password_hash="h", email=EmailAddress.from_input("a@example.test")
        )


def test_challenge_is_usable_until_expired_exhausted_or_consumed() -> None:
    challenge = AuthChallenge(
        challenge_id=UUID(int=1),
        purpose=ChallengePurpose.MFA,
        token_hash="e" * 64,
        user_id=UUID(int=2),
        clinic_id=None,
        invitation_id=None,
        expires_at=NOW + timedelta(minutes=5),
        max_attempts=2,
    )

    assert challenge.is_usable(purpose=ChallengePurpose.MFA, now=NOW)
    assert not challenge.is_usable(purpose=ChallengePurpose.ACTIVATION, now=NOW)
    assert not challenge.is_usable(
        purpose=ChallengePurpose.MFA, now=NOW + timedelta(minutes=5)
    )
    exhausted = challenge.with_failed_attempt().with_failed_attempt()
    assert not exhausted.is_usable(purpose=ChallengePurpose.MFA, now=NOW)
    assert not challenge.consumed(now=NOW).is_usable(
        purpose=ChallengePurpose.MFA, now=NOW
    )


def test_unknown_permission_codes_grant_nothing() -> None:
    granted = PermissionCode.known(["glucose.write_own", "made.up_permission"])

    assert granted == {PermissionCode.GLUCOSE_WRITE_OWN}
