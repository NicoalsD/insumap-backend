from dataclasses import replace
from datetime import timedelta

import pytest

from insumap.application.common.actor import Actor
from insumap.application.identity.authenticate import SessionScope
from insumap.application.identity.login import LoginInput
from insumap.application.identity.mfa import (
    ConfirmMfaEnrollmentInput,
    StartMfaEnrollmentInput,
    VerifyMfaChallengeInput,
)
from insumap.application.identity.ports import CodePurpose
from insumap.application.identity.session import AuthenticationResult
from insumap.application.security.events import SecurityEventType
from insumap.application.security.rate_limit import RateLimitedError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import (
    AccountNotActiveError,
    ClinicSuspendedError,
    InvalidCredentialsError,
    InvalidStateTransitionError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from insumap.domain.identity.session import LoginStatus
from insumap.domain.identity.user import ClinicSummary
from tests.support.identity_fakes import VALID_TOTP
from tests.support.identity_world import (
    CLINIC,
    DOCTOR_USER,
    ENROLLING_DOCTOR,
    PASSWORD,
    PATIENT_USER,
    IdentityWorld,
)

IP = "203.0.113.7"


def login(
    world: IdentityWorld, email: str, password: str = PASSWORD
) -> AuthenticationResult:
    return world.login.execute(LoginInput(email=email, password=password, client_ip=IP))


def actor_of(world: IdentityWorld, token: str) -> Actor:
    return world.authenticate.execute(token, SessionScope.ANY)


def test_patient_login_opens_a_full_session() -> None:
    world = IdentityWorld()

    result = login(world, "  Paciente@EXAMPLE.test ")

    assert result.status is LoginStatus.AUTHENTICATED
    assert result.session is not None
    assert result.session.refresh_token is not None
    claims = world.tokens.decode(result.session.access_token)
    assert claims.amr == ("pwd",)
    assert claims.session_id is not None
    assert world.uow.commits == 1
    assert world.limiter.hits == [("test", IP)]


def test_staff_with_mfa_gets_a_challenge_and_no_session() -> None:
    world = IdentityWorld()

    result = login(world, "medico@example.test")

    assert result.status is LoginStatus.MFA_CHALLENGE
    assert result.challenge_token is not None
    assert result.session is None
    assert not world.refresh_tokens.tokens


def test_staff_without_factor_gets_an_enrollment_session_without_refresh() -> None:
    world = IdentityWorld()

    result = login(world, "nuevo@example.test")

    assert result.status is LoginStatus.MFA_ENROLLMENT_REQUIRED
    assert result.session is not None
    assert result.session.refresh_token is None
    assert world.tokens.decode(result.session.access_token).session_id is None
    assert not world.refresh_tokens.tokens


@pytest.mark.parametrize("email", ["paciente@example.test", "nadie@example.test"])
def test_exactly_one_hash_verification_per_attempt(email: str) -> None:
    world = IdentityWorld()

    with pytest.raises(InvalidCredentialsError):
        login(world, email, "wrong password entirely")

    assert world.hasher.verifications == 1


def test_account_without_password_is_generic_and_still_verifies_once() -> None:
    world = IdentityWorld()
    world.users.add(
        replace(
            world.users.accounts[PATIENT_USER],
            password_hash=None,
            status=AccountStatus.INVITED,
        )
    )

    with pytest.raises(InvalidCredentialsError):
        login(world, "paciente@example.test")

    assert world.hasher.verifications == 1


def test_inactive_account_is_told_only_after_the_right_password() -> None:
    world = IdentityWorld()
    world.users.add(
        replace(world.users.accounts[PATIENT_USER], status=AccountStatus.SUSPENDED)
    )

    with pytest.raises(AccountNotActiveError):
        login(world, "paciente@example.test")
    with pytest.raises(InvalidCredentialsError):
        login(world, "paciente@example.test", "wrong password entirely")


def test_ended_membership_is_not_active() -> None:
    world = IdentityWorld()
    world.users.add(
        replace(world.users.accounts[PATIENT_USER], membership_active=False)
    )

    with pytest.raises(AccountNotActiveError):
        login(world, "paciente@example.test")


def test_suspended_clinic_blocks_login() -> None:
    world = IdentityWorld()
    suspended = ClinicSummary(
        clinic_id=CLINIC.clinic_id, name="x", is_demo=True, is_active=False
    )
    world.users.add(replace(world.users.accounts[PATIENT_USER], clinic=suspended))

    with pytest.raises(ClinicSuspendedError):
        login(world, "paciente@example.test")


def test_stale_hash_is_rehashed_after_a_correct_password() -> None:
    world = IdentityWorld()
    world.users.add(
        replace(
            world.users.accounts[PATIENT_USER],
            password_hash=f"stale:{PASSWORD}",
        )
    )

    login(world, "paciente@example.test")

    assert world.users.accounts[PATIENT_USER].password_hash == f"hashed:{PASSWORD}"


def test_login_is_rate_limited_before_touching_the_database() -> None:
    world = IdentityWorld()
    world.limiter.blocked = True

    with pytest.raises(RateLimitedError):
        login(world, "paciente@example.test")

    assert world.uow.commits == 0
    assert world.hasher.verifications == 0


def mfa_token(world: IdentityWorld) -> str:
    token = login(world, "medico@example.test").challenge_token
    assert token is not None
    return token


def verify(world: IdentityWorld, token: str, code: str) -> AuthenticationResult:
    return world.verify_mfa.execute(
        VerifyMfaChallengeInput(challenge_token=token, code=code, client_ip=IP)
    )


def test_totp_completes_the_login_with_otp_in_amr() -> None:
    world = IdentityWorld()
    token = mfa_token(world)

    result = verify(world, token, VALID_TOTP)

    assert result.status is LoginStatus.AUTHENTICATED
    assert result.session is not None
    claims = world.tokens.decode(result.session.access_token)
    assert claims.amr == ("pwd", "otp")
    assert len(world.refresh_tokens.tokens) == 1


def test_challenge_is_single_use_and_totp_step_is_not_replayable() -> None:
    world = IdentityWorld()
    token = mfa_token(world)
    verify(world, token, VALID_TOTP)

    with pytest.raises(UnauthenticatedError):
        verify(world, token, VALID_TOTP)
    second = mfa_token(world)
    with pytest.raises(InvalidCredentialsError):
        verify(world, second, VALID_TOTP)


def test_wrong_code_counts_an_attempt_and_is_committed() -> None:
    world = IdentityWorld()
    token = mfa_token(world)
    commits = world.uow.commits

    with pytest.raises(InvalidCredentialsError):
        verify(world, token, "000000")

    assert world.uow.commits == commits + 1
    assert next(iter(world.challenge_repo.challenges.values())).attempts == 1
    assert world.events.events[-1].event_type is SecurityEventType.MFA_FAILED


def test_challenge_is_exhausted_after_five_failures() -> None:
    world = IdentityWorld()
    token = mfa_token(world)
    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            verify(world, token, "000000")

    with pytest.raises(UnauthenticatedError):
        verify(world, token, VALID_TOTP)


def test_challenge_expires_after_five_minutes() -> None:
    world = IdentityWorld()
    token = mfa_token(world)
    world.clock.advance(timedelta(minutes=5))

    with pytest.raises(UnauthenticatedError):
        verify(world, token, VALID_TOTP)


def test_unknown_challenge_is_unauthenticated() -> None:
    with pytest.raises(UnauthenticatedError):
        verify(IdentityWorld(), "nope", VALID_TOTP)


def test_recovery_code_works_once_and_is_recorded() -> None:
    world = IdentityWorld()
    stored = world.code_hasher.hash_for_storage(
        CodePurpose.RECOVERY,
        "ABCDEFGHJK",
    )
    world.factors.recovery[DOCTOR_USER] = [stored.value]

    result = verify(world, mfa_token(world), "abcde-fghjk")

    assert result.status is LoginStatus.AUTHENTICATED
    assert (
        world.events.events[-1].event_type is SecurityEventType.MFA_RECOVERY_CODE_USED
    )
    with pytest.raises(InvalidCredentialsError):
        verify(world, mfa_token(world), "abcde-fghjk")


def enrollment_actor(world: IdentityWorld) -> Actor:
    result = login(world, "nuevo@example.test")
    assert result.session is not None
    return actor_of(world, result.session.access_token)


def test_enrollment_stores_the_secret_encrypted_and_confirms_with_a_totp() -> None:
    world = IdentityWorld()
    actor = enrollment_actor(world)

    started = world.start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))

    assert started.otpauth_uri.startswith("otpauth://totp/Insumap:nuevo@example.test")
    factor = world.factors.find_totp(ENROLLING_DOCTOR)
    assert factor is not None
    assert not factor.is_confirmed
    assert started.secret.encode() not in factor.secret.ciphertext.split(b"#")[0]

    confirmed = world.confirm_enrollment.execute(
        ConfirmMfaEnrollmentInput(actor=actor, code=VALID_TOTP, client_ip=IP)
    )

    assert confirmed.authentication.status is LoginStatus.AUTHENTICATED
    assert len(confirmed.recovery_codes) == 10
    assert len(set(confirmed.recovery_codes)) == 10
    assert len(world.factors.recovery[ENROLLING_DOCTOR]) == 10
    assert all(
        v.startswith("hmac-RECOVERY-") for v in world.factors.recovery[ENROLLING_DOCTOR]
    )
    factor = world.factors.find_totp(ENROLLING_DOCTOR)
    assert factor is not None
    assert factor.is_confirmed


def test_restarting_replaces_an_abandoned_enrollment() -> None:
    world = IdentityWorld()
    actor = enrollment_actor(world)
    world.start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))
    first = world.factors.find_totp(ENROLLING_DOCTOR)

    world.start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))

    assert first is not None
    assert first.factor_id in world.factors.revoked
    assert world.factors.find_totp(ENROLLING_DOCTOR) != first


def test_confirm_with_a_wrong_code_fails_and_keeps_the_factor_unconfirmed() -> None:
    world = IdentityWorld()
    actor = enrollment_actor(world)
    world.start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))

    with pytest.raises(InvalidCredentialsError):
        world.confirm_enrollment.execute(
            ConfirmMfaEnrollmentInput(actor=actor, code="999999", client_ip=IP)
        )

    factor = world.factors.find_totp(ENROLLING_DOCTOR)
    assert factor is not None
    assert not factor.is_confirmed


def test_confirm_without_start_and_double_enrollment_are_state_errors() -> None:
    world = IdentityWorld()
    actor = enrollment_actor(world)
    with pytest.raises(InvalidStateTransitionError):
        world.confirm_enrollment.execute(
            ConfirmMfaEnrollmentInput(actor=actor, code=VALID_TOTP, client_ip=IP)
        )
    world.start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))
    world.confirm_enrollment.execute(
        ConfirmMfaEnrollmentInput(actor=actor, code=VALID_TOTP, client_ip=IP)
    )
    with pytest.raises(InvalidStateTransitionError):
        world.start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))
    with pytest.raises(InvalidStateTransitionError):
        world.confirm_enrollment.execute(
            ConfirmMfaEnrollmentInput(actor=actor, code=VALID_TOTP, client_ip=IP)
        )


def test_a_patient_cannot_enroll_in_mfa() -> None:
    world = IdentityWorld()
    result = login(world, "paciente@example.test")
    assert result.session is not None
    actor = actor_of(world, result.session.access_token)

    with pytest.raises(PermissionDeniedError):
        world.start_enrollment.execute(StartMfaEnrollmentInput(actor=actor))
    with pytest.raises(PermissionDeniedError):
        world.confirm_enrollment.execute(
            ConfirmMfaEnrollmentInput(actor=actor, code=VALID_TOTP, client_ip=IP)
        )
