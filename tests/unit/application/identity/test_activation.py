from datetime import date, timedelta
from uuid import UUID

import pytest

from insumap.application.identity.activation import (
    CompleteActivationInput,
    ConsentInput,
    VerifyActivationCodeInput,
    VerifyActivationCodeResult,
)
from insumap.application.security.events import SecurityEventType
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.consent import ConsentScope
from insumap.domain.identity.errors import (
    ConsentRequiredError,
    ConsentVersionOutdatedError,
    EmailUnavailableError,
    InvitationInvalidError,
    PasswordPolicyError,
)
from insumap.domain.identity.events import PatientActivated
from insumap.domain.identity.invitation import InvitationStatus
from insumap.domain.identity.session import LoginStatus
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.identity_world import (
    ACTIVATION_CODE,
    BIRTH_DATE,
    INVITATION_ID,
    INVITED_PATIENT,
    INVITED_USER,
    NEW_PASSWORD,
    NOTICE_ID,
    STAFF_CODE,
    STAFF_EMAIL,
    STAFF_INVITATION_ID,
    STAFF_INVITED_USER,
    IdentityWorld,
)

IP = "203.0.113.7"


def verify(
    world: IdentityWorld,
    code: str = ACTIVATION_CODE,
    birth_date: date | None = BIRTH_DATE,
) -> VerifyActivationCodeResult:
    return world.verify_activation.execute(
        VerifyActivationCodeInput(
            activation_code=code, birth_date=birth_date, client_ip=IP
        )
    )


def complete_input(
    token: str,
    *,
    password: str = NEW_PASSWORD,
    email: str | None = None,
    accepted: bool = True,
    notice: UUID = NOTICE_ID,
    ai: bool = False,
) -> CompleteActivationInput:
    return CompleteActivationInput(
        activation_token=token,
        new_password=password,
        email=email,
        consent=ConsentInput(
            privacy_notice_version_id=notice,
            accepted=accepted,
            ai_external_processing=ai,
        ),
        client_ip=IP,
    )


def test_verify_returns_the_session_without_personal_data() -> None:
    world = IdentityWorld()

    result = verify(world, "abcd efgh jkmn pqrs")

    assert result.clinic_name == "Clínica Demo"
    assert result.privacy_notice_version_id == NOTICE_ID
    assert not result.email_required
    assert world.activations.invitations[INVITATION_ID].status is (
        InvitationStatus.VERIFIED
    )
    assert "Ana" not in repr(result)


@pytest.mark.parametrize(
    "code", ["short", "ABCD-EFGH-JKMN-PQR!", "ZZZZ-ZZZZ-ZZZZ-ZZZZ"]
)
def test_every_bad_code_is_the_same_error(code: str) -> None:
    with pytest.raises(InvitationInvalidError):
        verify(IdentityWorld(), code)


def test_wrong_birth_date_counts_attempts_then_locks() -> None:
    world = IdentityWorld()
    for _ in range(4):
        with pytest.raises(InvitationInvalidError):
            verify(world, birth_date=date(2000, 1, 1))
    assert world.activations.invitations[INVITATION_ID].failed_attempts == 4

    with pytest.raises(InvitationInvalidError):
        verify(world, birth_date=None)

    assert world.activations.invitations[INVITATION_ID].status is (
        InvitationStatus.LOCKED
    )
    assert world.events.events[-1].event_type is SecurityEventType.ACTIVATION_LOCKED
    with pytest.raises(InvitationInvalidError):
        verify(world)


def test_expired_invitation_is_invalid() -> None:
    world = IdentityWorld()
    world.clock.advance(timedelta(days=8))

    with pytest.raises(InvitationInvalidError):
        verify(world)


def test_complete_activates_patient_and_records_consent_in_one_commit() -> None:
    world = IdentityWorld()
    token = verify(world).activation_token
    commits = world.uow.commits

    result = world.complete_activation.execute(complete_input(token, ai=True))

    assert result.status is LoginStatus.AUTHENTICATED
    assert result.session is not None
    assert world.uow.commits == commits + 1
    account = world.users.accounts[INVITED_USER]
    assert account.status is AccountStatus.ACTIVE
    assert account.email_normalized == "ana@example.test"
    assert account.password_hash == f"hashed:{NEW_PASSWORD}"
    assert world.activations.invitations[INVITATION_ID].status is (
        InvitationStatus.USED
    )
    scopes = {record.scope for record in world.consents.records}
    assert scopes == {
        ConsentScope.SENSITIVE_DATA_PROCESSING,
        ConsentScope.AI_EXTERNAL_PROCESSING,
    }
    assert world.history.hashes[INVITED_USER] == [f"hashed:{NEW_PASSWORD}"]
    published = [e for e in world.uow.published if isinstance(e, PatientActivated)]
    assert [e.patient_id for e in published] == [INVITED_PATIENT]
    assert world.events.events[-1].event_type is SecurityEventType.ACCOUNT_ACTIVATED


def test_the_activation_token_is_single_use() -> None:
    world = IdentityWorld()
    token = verify(world).activation_token
    world.complete_activation.execute(complete_input(token))

    with pytest.raises(InvitationInvalidError):
        world.complete_activation.execute(complete_input(token))


def test_unknown_token_is_invitation_invalid() -> None:
    with pytest.raises(InvitationInvalidError):
        IdentityWorld().complete_activation.execute(complete_input("nope"))


def test_consent_is_mandatory_and_must_be_the_current_version() -> None:
    world = IdentityWorld()
    token = verify(world).activation_token

    with pytest.raises(ConsentRequiredError):
        world.complete_activation.execute(complete_input(token, accepted=False))
    with pytest.raises(ConsentVersionOutdatedError):
        world.complete_activation.execute(complete_input(token, notice=UUID(int=1)))

    assert world.users.accounts[INVITED_USER].status is AccountStatus.INVITED
    assert not world.consents.records


def test_password_policy_violations_do_not_activate() -> None:
    world = IdentityWorld()
    token = verify(world).activation_token

    with pytest.raises(PasswordPolicyError):
        world.complete_activation.execute(complete_input(token, password="short"))

    assert world.users.accounts[INVITED_USER].status is AccountStatus.INVITED


def test_taken_email_is_refused() -> None:
    world = IdentityWorld()
    token = verify(world).activation_token

    with pytest.raises(EmailUnavailableError):
        world.complete_activation.execute(
            complete_input(token, email="Paciente@example.test")
        )


def test_email_is_required_when_the_import_had_none() -> None:
    world = IdentityWorld()
    profile = world.activations.profiles[INVITED_PATIENT]
    world.activations.profiles[INVITED_PATIENT] = type(profile)(
        patient_id=profile.patient_id,
        clinic_name=profile.clinic_name,
        birth_date=profile.birth_date,
        full_name=profile.full_name,
        contact_email=None,
    )
    result = verify(world)
    assert result.email_required

    with pytest.raises(InsumapError) as caught:
        world.complete_activation.execute(complete_input(result.activation_token))
    assert caught.value.code is ErrorCode.VALIDATION_ERROR

    done = world.complete_activation.execute(
        complete_input(result.activation_token, email="otra@example.test")
    )
    assert done.status is LoginStatus.AUTHENTICATED


# Staff activation (STAFF_ACTIVATION).


def staff_complete(token: str, **overrides: object) -> CompleteActivationInput:
    fields: dict[str, object] = {
        "activation_token": token,
        "new_password": NEW_PASSWORD,
        "email": None,
        "consent": None,
        "client_ip": IP,
    }
    return CompleteActivationInput(**(fields | overrides))  # type: ignore[arg-type]


def test_staff_verify_needs_no_birth_date_and_no_notice() -> None:
    world = IdentityWorld()

    result = verify(world, STAFF_CODE, birth_date=None)

    assert result.clinic_name == "Clínica Demo"
    assert result.privacy_notice_version_id is None
    assert not result.email_required
    assert world.activations.invitations[STAFF_INVITATION_ID].status is (
        InvitationStatus.VERIFIED
    )


def test_staff_verify_ignores_a_birth_date_and_never_counts_attempts() -> None:
    world = IdentityWorld()

    verify(world, STAFF_CODE, birth_date=date(2000, 1, 1))

    invitation = world.activations.invitations[STAFF_INVITATION_ID]
    assert invitation.status is InvitationStatus.VERIFIED
    assert invitation.failed_attempts == 0


def test_staff_complete_activates_and_requires_mfa_enrollment() -> None:
    world = IdentityWorld()
    token = verify(world, STAFF_CODE, birth_date=None).activation_token
    commits = world.uow.commits

    result = world.complete_activation.execute(staff_complete(token))

    assert result.status is LoginStatus.MFA_ENROLLMENT_REQUIRED
    assert result.session is not None
    assert result.session.refresh_token is None
    assert world.uow.commits == commits + 1
    account = world.users.accounts[STAFF_INVITED_USER]
    assert account.status is AccountStatus.ACTIVE
    assert account.email == STAFF_EMAIL
    assert account.password_hash == f"hashed:{NEW_PASSWORD}"
    assert world.activations.invitations[STAFF_INVITATION_ID].status is (
        InvitationStatus.USED
    )
    assert not world.consents.records
    assert not [e for e in world.uow.published if isinstance(e, PatientActivated)]
    assert world.events.events[-1].event_type is SecurityEventType.ACCOUNT_ACTIVATED


def test_staff_complete_ignores_the_email_and_the_consent_of_the_body() -> None:
    world = IdentityWorld()
    token = verify(world, STAFF_CODE, birth_date=None).activation_token

    world.complete_activation.execute(
        complete_input(token, email="otro@example.test", accepted=False)
    )

    account = world.users.accounts[STAFF_INVITED_USER]
    assert account.status is AccountStatus.ACTIVE
    assert account.email == STAFF_EMAIL


def test_staff_activation_token_is_single_use_and_the_code_expires() -> None:
    world = IdentityWorld()
    token = verify(world, STAFF_CODE, birth_date=None).activation_token
    world.complete_activation.execute(staff_complete(token))

    with pytest.raises(InvitationInvalidError):
        world.complete_activation.execute(staff_complete(token))
    with pytest.raises(InvitationInvalidError):
        verify(world, STAFF_CODE, birth_date=None)
    other = IdentityWorld()
    other.clock.advance(timedelta(days=8))
    with pytest.raises(InvitationInvalidError):
        verify(other, STAFF_CODE, birth_date=None)


def test_staff_password_policy_violation_does_not_activate() -> None:
    world = IdentityWorld()
    token = verify(world, STAFF_CODE, birth_date=None).activation_token

    with pytest.raises(PasswordPolicyError):
        world.complete_activation.execute(staff_complete(token, new_password="short"))

    assert world.users.accounts[STAFF_INVITED_USER].status is AccountStatus.INVITED


def test_a_patient_must_still_send_the_consent() -> None:
    world = IdentityWorld()
    token = verify(world).activation_token

    with pytest.raises(InsumapError) as caught:
        world.complete_activation.execute(staff_complete(token))

    assert caught.value.code is ErrorCode.VALIDATION_ERROR
    assert world.users.accounts[INVITED_USER].status is AccountStatus.INVITED
