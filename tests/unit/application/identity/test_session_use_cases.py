from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.common.actor import Actor
from insumap.application.identity.authenticate import SessionScope
from insumap.application.identity.current_user import GetCurrentUserInput
from insumap.application.identity.login import LoginInput
from insumap.application.identity.mfa import VerifyMfaChallengeInput
from insumap.application.identity.session import SessionTokens
from insumap.application.identity.sessions import (
    LogoutAllInput,
    LogoutInput,
    RefreshSessionInput,
)
from insumap.application.security.events import SecurityEventType
from insumap.application.security.rate_limit import RateLimitedError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import (
    ClinicSuspendedError,
    MfaRequiredError,
    SessionRevokedError,
    UnauthenticatedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.domain.identity.user import ClinicSummary
from tests.support.identity_fakes import VALID_TOTP
from tests.support.identity_world import (
    CLINIC,
    DOCTOR_USER,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
    IdentityWorld,
)

IP = "203.0.113.7"


def patient_session(world: IdentityWorld) -> SessionTokens:
    result = world.login.execute(
        LoginInput(email="paciente@example.test", password=PASSWORD, client_ip=IP)
    )
    assert result.session is not None
    return result.session


def refresh(world: IdentityWorld, token: str | None) -> SessionTokens:
    assert token is not None
    return world.refresh.execute(RefreshSessionInput(refresh_token=token))


def test_refresh_rotates_the_token_inside_the_same_family() -> None:
    world = IdentityWorld()
    first = patient_session(world)

    second = refresh(world, first.refresh_token)

    assert second.refresh_token != first.refresh_token
    stored = list(world.refresh_tokens.tokens.values())
    assert len(stored) == 2
    old, new = stored
    assert old.revoked_reason is RevocationReason.ROTATED
    assert old.replaced_by_id == new.token_id
    assert old.family_id == new.family_id
    claims = world.tokens.decode(second.access_token)
    assert claims.session_id == old.family_id


def test_reusing_a_rotated_token_revokes_the_family_and_bumps_the_version() -> None:
    world = IdentityWorld()
    first = patient_session(world)
    second = refresh(world, first.refresh_token)
    commits = world.uow.commits

    with pytest.raises(SessionRevokedError):
        refresh(world, first.refresh_token)

    assert world.uow.commits == commits + 1
    assert all(t.is_revoked for t in world.refresh_tokens.tokens.values())
    assert world.users.accounts[PATIENT_USER].token_version == 1
    assert (
        world.events.events[-1].event_type
        is SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED
    )
    with pytest.raises(SessionRevokedError):
        refresh(world, second.refresh_token)


def test_unknown_and_expired_tokens_are_plain_unauthenticated() -> None:
    world = IdentityWorld()
    first = patient_session(world)
    with pytest.raises(UnauthenticatedError):
        refresh(world, "never-issued")
    world.clock.advance(timedelta(days=31))

    with pytest.raises(UnauthenticatedError):
        refresh(world, first.refresh_token)

    assert world.uow.commits == 1  # only the login: an expired claim is rolled back


def test_refresh_stops_for_deactivated_accounts_and_suspended_clinics() -> None:
    world = IdentityWorld()
    first = patient_session(world)
    original = world.users.accounts[PATIENT_USER]
    world.users.add(replace(original, status=AccountStatus.SUSPENDED))
    with pytest.raises(SessionRevokedError):
        refresh(world, first.refresh_token)

    world = IdentityWorld()
    first = patient_session(world)
    suspended = ClinicSummary(
        clinic_id=CLINIC.clinic_id, name="x", is_demo=True, is_active=False
    )
    world.users.add(replace(world.users.accounts[PATIENT_USER], clinic=suspended))
    with pytest.raises(ClinicSuspendedError):
        refresh(world, first.refresh_token)


def test_refresh_is_rate_limited_per_user() -> None:
    world = IdentityWorld()
    first = patient_session(world)
    world.limiter.blocked = True

    with pytest.raises(RateLimitedError):
        refresh(world, first.refresh_token)

    assert world.limiter.hits[-1] == ("test", str(PATIENT_USER))


def actor_for(world: IdentityWorld, session: SessionTokens) -> Actor:
    return world.authenticate.execute(session.access_token, SessionScope.FULL)


def test_logout_revokes_only_the_family_of_this_device() -> None:
    world = IdentityWorld()
    mine = patient_session(world)
    other = patient_session(world)

    world.logout.execute(
        LogoutInput(actor=actor_for(world, mine), refresh_token=mine.refresh_token)
    )

    tokens = list(world.refresh_tokens.tokens.values())
    assert [t.revoked_reason for t in tokens] == [RevocationReason.LOGOUT, None]
    refresh(world, other.refresh_token)


def test_logout_uses_the_session_id_when_there_is_no_cookie() -> None:
    world = IdentityWorld()
    mine = patient_session(world)

    world.logout.execute(LogoutInput(actor=actor_for(world, mine), refresh_token=None))

    assert all(t.is_revoked for t in world.refresh_tokens.tokens.values())


def test_logout_ignores_a_cookie_of_someone_else() -> None:
    world = IdentityWorld()
    mine = patient_session(world)
    doctor_token = world.login.execute(
        LoginInput(email="medico@example.test", password=PASSWORD, client_ip=IP)
    ).challenge_token
    assert doctor_token is not None
    other = world.verify_mfa.execute(
        VerifyMfaChallengeInput(
            challenge_token=doctor_token, code=VALID_TOTP, client_ip=IP
        )
    ).session
    assert other is not None

    world.logout.execute(
        LogoutInput(actor=actor_for(world, mine), refresh_token=other.refresh_token)
    )

    revoked = [t for t in world.refresh_tokens.tokens.values() if t.is_revoked]
    assert [t.user_id for t in revoked] == [PATIENT_USER]


def test_enrollment_session_can_log_out_without_a_family() -> None:
    world = IdentityWorld()
    result = world.login.execute(
        LoginInput(email="nuevo@example.test", password=PASSWORD, client_ip=IP)
    )
    assert result.session is not None
    actor = world.authenticate.execute(result.session.access_token, SessionScope.ANY)

    world.logout.execute(LogoutInput(actor=actor, refresh_token=None))

    assert not world.refresh_tokens.tokens


def test_logout_all_revokes_every_family_and_kills_access_tokens() -> None:
    world = IdentityWorld()
    first = patient_session(world)
    patient_session(world)
    actor = actor_for(world, first)

    world.logout_all.execute(LogoutAllInput(actor=actor))

    assert all(
        t.revoked_reason is RevocationReason.LOGOUT_ALL
        for t in world.refresh_tokens.tokens.values()
    )
    assert world.users.accounts[PATIENT_USER].token_version == 1
    assert world.events.events[-1].event_type is SecurityEventType.SESSIONS_REVOKED
    with pytest.raises(SessionRevokedError):
        world.authenticate.execute(first.access_token, SessionScope.FULL)


def test_authenticate_reads_permissions_from_the_database() -> None:
    world = IdentityWorld()
    session = patient_session(world)

    actor = actor_for(world, session)

    assert actor.permissions == {PermissionCode.PATIENTS_READ_OWN}
    assert actor.patient_id == PATIENT_ID
    assert actor.clinic_id == CLINIC.clinic_id
    assert not actor.requires_mfa


def test_authenticate_rejects_unknown_tokens_and_wrong_versions() -> None:
    world = IdentityWorld()
    session = patient_session(world)
    with pytest.raises(UnauthenticatedError):
        world.authenticate.execute("garbage", SessionScope.FULL)
    grant = world.tokens.grants[session.access_token]
    world.tokens.grants["old"] = replace(grant, token_version=9)
    with pytest.raises(SessionRevokedError):
        world.authenticate.execute("old", SessionScope.FULL)
    world.users.accounts.pop(PATIENT_USER)
    with pytest.raises(SessionRevokedError):
        world.authenticate.execute(session.access_token, SessionScope.FULL)


def test_staff_without_otp_is_denied_except_in_enrollment_scope() -> None:
    world = IdentityWorld()
    result = world.login.execute(
        LoginInput(email="nuevo@example.test", password=PASSWORD, client_ip=IP)
    )
    assert result.session is not None
    token = result.session.access_token

    with pytest.raises(MfaRequiredError):
        world.authenticate.execute(token, SessionScope.FULL)
    for scope in (SessionScope.ENROLLMENT, SessionScope.ANY):
        assert not world.authenticate.execute(token, scope).mfa_verified


def test_authenticate_rejects_a_suspended_clinic() -> None:
    world = IdentityWorld()
    session = patient_session(world)
    suspended = ClinicSummary(
        clinic_id=CLINIC.clinic_id, name="x", is_demo=True, is_active=False
    )
    world.users.add(replace(world.users.accounts[PATIENT_USER], clinic=suspended))

    with pytest.raises(ClinicSuspendedError):
        world.authenticate.execute(session.access_token, SessionScope.FULL)


def test_current_user_shape_and_pending_consent() -> None:
    world = IdentityWorld()
    session = patient_session(world)
    actor = actor_for(world, session)

    me = world.current_user.execute(GetCurrentUserInput(actor=actor))

    assert me.user_id == PATIENT_USER
    assert me.email == "paciente@example.test"
    assert me.clinic == CLINIC
    assert me.permissions == ("patients.read_own",)
    assert not me.mfa_enabled
    assert me.consent_required


def test_current_user_of_staff_reports_mfa_and_no_consent() -> None:
    world = IdentityWorld()
    challenge = world.login.execute(
        LoginInput(email="medico@example.test", password=PASSWORD, client_ip=IP)
    ).challenge_token
    assert challenge is not None
    session = world.verify_mfa.execute(
        VerifyMfaChallengeInput(
            challenge_token=challenge, code=VALID_TOTP, client_ip=IP
        )
    ).session
    assert session is not None

    me = world.current_user.execute(
        GetCurrentUserInput(actor=actor_for(world, session))
    )

    assert me.user_id == DOCTOR_USER
    assert me.mfa_enabled
    assert not me.consent_required


def test_current_user_of_a_missing_account_is_revoked() -> None:
    world = IdentityWorld()
    actor = Actor(
        user_id=UUID(int=999),
        clinic_id=None,
        role=world.users.accounts[PATIENT_USER].role,
    )

    with pytest.raises(SessionRevokedError):
        world.current_user.execute(GetCurrentUserInput(actor=actor))
