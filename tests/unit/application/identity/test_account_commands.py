"""Recovery code regeneration and password change, as commands (P13, P09)."""

from dataclasses import replace
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.common.actor import Actor
from insumap.application.identity.change_password import (
    ChangePasswordCommand,
    ChangePasswordCommandHandler,
)
from insumap.application.identity.recovery_codes import (
    RegenerateMfaRecoveryCodesCommand,
    RegenerateMfaRecoveryCodesCommandHandler,
)
from insumap.application.security.events import SecurityEventType
from insumap.application.security.rate_limit import RateLimitCheck, RateLimitedError
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.errors import (
    ConsentRequiredError,
    InvalidCredentialsError,
    PasswordPolicyError,
    PermissionDeniedError,
)
from insumap.domain.identity.refresh_token import RevocationReason
from insumap.domain.identity.roles import Role
from tests.support.commands import InMemoryAuditLog
from tests.support.identity_fakes import HASH_PREFIX, VALID_TOTP, FakeRecoveryCodes
from tests.support.identity_world import (
    CLINIC,
    DOCTOR_USER,
    NEW_PASSWORD,
    NOTICE_ID,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
    RULE,
    IdentityWorld,
)


def doctor_actor() -> Actor:
    return Actor(
        user_id=DOCTOR_USER,
        clinic_id=CLINIC.clinic_id,
        role=Role.DOCTOR,
        requires_mfa=True,
        mfa_verified=True,
    )


def patient_actor() -> Actor:
    return Actor(
        user_id=PATIENT_USER,
        clinic_id=CLINIC.clinic_id,
        role=Role.PATIENT,
        patient_id=PATIENT_ID,
    )


def recovery_handler(world: IdentityWorld) -> RegenerateMfaRecoveryCodesCommandHandler:
    return RegenerateMfaRecoveryCodesCommandHandler(
        factors=world.factors,
        verifier=world.verifier,
        generator=FakeRecoveryCodes(),
        code_count=10,
        code_hasher=world.code_hasher,
        rate_limit=RateLimitCheck(world.limiter, RULE),
        clock=world.clock,
    )


def password_handler(world: IdentityWorld) -> ChangePasswordCommandHandler:
    return ChangePasswordCommandHandler(
        users=world.users,
        hasher=world.hasher,
        passwords=world.passwords,
        refresh_tokens=world.refresh_tokens,
        sessions=world.sessions,
        consents=world.consents,
        events=world.events,
        rate_limit=RateLimitCheck(world.limiter, RULE),
        clock=world.clock,
    )


def accept_current_notice(world: IdentityWorld) -> None:
    world.consents.records.append(
        ConsentRecord(
            consent_id=UUID(int=5),
            clinic_id=CLINIC.clinic_id,
            patient_id=PATIENT_ID,
            privacy_notice_version_id=NOTICE_ID,
            scope=ConsentScope.SENSITIVE_DATA_PROCESSING,
            action=ConsentAction.ACCEPTED,
            occurred_at=world.clock.now(),
            recorded_by=PATIENT_USER,
        )
    )


# Recovery codes.


def test_a_valid_totp_replaces_the_codes_and_returns_the_new_ones_formatted() -> None:
    world = IdentityWorld()

    result = recovery_handler(world).handle(
        RegenerateMfaRecoveryCodesCommand(actor=doctor_actor(), code=VALID_TOTP)
    )

    assert result.user_id == DOCTOR_USER
    assert len(result.recovery_codes) == 10
    assert result.recovery_codes[0] == "00000-00001"
    stored = world.factors.recovery[DOCTOR_USER]
    assert len(stored) == 10
    assert all(value.startswith("hmac-RECOVERY-") for value in stored)


@pytest.mark.parametrize("code", ["000000", "00000-00001", "abcdef"])
def test_only_a_correct_totp_counts_and_nothing_changes_otherwise(code: str) -> None:
    world = IdentityWorld()

    with pytest.raises(InvalidCredentialsError):
        recovery_handler(world).handle(
            RegenerateMfaRecoveryCodesCommand(actor=doctor_actor(), code=code)
        )

    assert DOCTOR_USER not in world.factors.recovery


def test_a_patient_has_no_second_factor_to_regenerate() -> None:
    with pytest.raises(PermissionDeniedError):
        recovery_handler(IdentityWorld()).handle(
            RegenerateMfaRecoveryCodesCommand(actor=patient_actor(), code=VALID_TOTP)
        )


def test_staff_without_a_confirmed_factor_is_denied() -> None:
    world = IdentityWorld()
    actor = replace(doctor_actor(), user_id=UUID(int=31))

    with pytest.raises(PermissionDeniedError):
        recovery_handler(world).handle(
            RegenerateMfaRecoveryCodesCommand(actor=actor, code=VALID_TOTP)
        )


def test_the_attempts_are_rate_limited_before_the_code_is_checked() -> None:
    world = IdentityWorld()
    world.limiter.blocked = True

    with pytest.raises(RateLimitedError):
        recovery_handler(world).handle(
            RegenerateMfaRecoveryCodesCommand(actor=doctor_actor(), code=VALID_TOTP)
        )

    assert world.limiter.hits == [("test", str(DOCTOR_USER))]


def test_the_regeneration_is_audited_without_the_codes() -> None:
    world, log = IdentityWorld(), InMemoryAuditLog()
    handler = AuditingCommandHandler(recovery_handler(world), log, world.clock)

    result = handler.handle(
        RegenerateMfaRecoveryCodesCommand(actor=doctor_actor(), code=VALID_TOTP)
    )

    [entry] = log.entries
    assert entry.action == "MFA_RECOVERY_CODES_REGENERATED"
    assert entry.entity_id == DOCTOR_USER
    assert entry.changed_fields == ("recovery_codes",)
    assert result.recovery_codes[0] not in repr(entry)


# Password change.


def test_a_password_change_ends_every_session_and_opens_a_new_one() -> None:
    world = IdentityWorld()
    accept_current_notice(world)
    old = world.sessions.open_full_session(world.users.accounts[PATIENT_USER])
    assert old.session is not None

    result = password_handler(world).handle(
        ChangePasswordCommand(
            actor=patient_actor(), current_password=PASSWORD, new_password=NEW_PASSWORD
        )
    )

    account = world.users.accounts[PATIENT_USER]
    assert account.password_hash == f"{HASH_PREFIX}{NEW_PASSWORD}"
    assert account.token_version == 1
    claims = world.tokens.decode(result.authentication.session.access_token)  # type: ignore[union-attr]
    assert claims.token_version == 1
    families = [
        token
        for token in world.refresh_tokens.tokens.values()
        if token.revoked_reason is RevocationReason.PASSWORD_CHANGED
    ]
    assert len(families) == 1
    live = [t for t in world.refresh_tokens.tokens.values() if not t.is_revoked]
    assert len(live) == 1
    assert world.history.hashes[PATIENT_USER][-1] == f"{HASH_PREFIX}{NEW_PASSWORD}"
    assert [e.event_type for e in world.events.events] == [
        SecurityEventType.PASSWORD_CHANGED
    ]


def test_a_wrong_current_password_changes_nothing() -> None:
    world = IdentityWorld()
    accept_current_notice(world)

    with pytest.raises(InvalidCredentialsError):
        password_handler(world).handle(
            ChangePasswordCommand(
                actor=patient_actor(),
                current_password="not the password at all",
                new_password=NEW_PASSWORD,
            )
        )

    assert world.users.accounts[PATIENT_USER].token_version == 0


def test_the_policy_rejects_a_weak_or_reused_new_password() -> None:
    world = IdentityWorld()
    accept_current_notice(world)
    world.history.hashes[PATIENT_USER] = [f"{HASH_PREFIX}{NEW_PASSWORD}"]

    with pytest.raises(PasswordPolicyError) as short:
        password_handler(world).handle(
            ChangePasswordCommand(
                actor=patient_actor(), current_password=PASSWORD, new_password="short"
            )
        )
    with pytest.raises(PasswordPolicyError) as reused:
        password_handler(world).handle(
            ChangePasswordCommand(
                actor=patient_actor(),
                current_password=PASSWORD,
                new_password=NEW_PASSWORD,
            )
        )

    assert "PASSWORD_TOO_SHORT" in short.value.violations
    assert "PASSWORD_REUSED" in reused.value.violations


def test_a_patient_with_a_pending_consent_cannot_change_the_password() -> None:
    with pytest.raises(ConsentRequiredError):
        password_handler(IdentityWorld()).handle(
            ChangePasswordCommand(
                actor=patient_actor(),
                current_password=PASSWORD,
                new_password=NEW_PASSWORD,
            )
        )


def test_the_passwords_never_reach_the_representation_of_the_command() -> None:
    command = ChangePasswordCommand(
        actor=patient_actor(), current_password=PASSWORD, new_password=NEW_PASSWORD
    )

    assert PASSWORD not in repr(command)
    assert NEW_PASSWORD not in repr(command)
