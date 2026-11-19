import base64
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
import pytest
from pydantic import SecretStr

from insumap.application.identity.ports import (
    AccessGrant,
    CodePurpose,
    EncryptedSecret,
)
from insumap.application.security.rate_limit import RateLimitRule
from insumap.domain.identity.errors import UnauthenticatedError
from insumap.domain.identity.roles import Role
from insumap.infrastructure.security.code_hasher import HmacCodeHasher
from insumap.infrastructure.security.jwt_service import JwtConfig, JwtTokenService
from insumap.infrastructure.security.keys import KeyRing
from insumap.infrastructure.security.opaque_tokens import Sha256OpaqueTokens
from insumap.infrastructure.security.password_hasher import (
    Argon2PasswordHasher,
    PasswordHashingConfig,
)
from insumap.infrastructure.security.rate_limiter import InMemoryRateLimiter
from insumap.infrastructure.security.recovery_codes import (
    CrockfordRecoveryCodeGenerator,
)
from insumap.infrastructure.security.secret_cipher import (
    AesGcmSecretCipher,
    SecretDecryptionError,
)
from insumap.infrastructure.security.totp import PyOtpTotp
from insumap.infrastructure.security.uuid7 import Uuid7Generator
from insumap.shared.config import Settings
from tests.support.fixed_clock import FixedClock
from tests.support.settings import (
    TEST_CODE_HMAC_KEY,
    TEST_JWT_SECRET,
    TEST_JWT_SECRET_PREVIOUS,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
USER = uuid.UUID(int=1)
GRANT = AccessGrant(
    user_id=USER,
    role=Role.DOCTOR,
    clinic_id=uuid.UUID(int=2),
    token_version=3,
    session_id=uuid.UUID(int=4),
    amr=("pwd", "otp"),
)


def ring(current: str = TEST_JWT_SECRET, previous: str | None = None) -> KeyRing:
    return KeyRing(
        current=SecretStr(current),
        previous=None if previous is None else SecretStr(previous),
    )


def jwt_service(clock: FixedClock, keys: KeyRing | None = None) -> JwtTokenService:
    return JwtTokenService(
        keys=keys or ring(),
        config=JwtConfig(
            issuer="insumap-api",
            audience="insumap-web",
            access_ttl=timedelta(minutes=15),
            leeway=timedelta(seconds=30),
        ),
        clock=clock,
    )


# KeyRing.


def test_key_ring_orders_current_first_and_rejects_unknown_ids() -> None:
    keys = ring(previous=TEST_JWT_SECRET_PREVIOUS)

    ids = [key_id for key_id, _ in keys.all_keys()]

    assert ids[0] == keys.current_key_id
    assert len(ids) == 2
    assert keys.verification_key(ids[1]) != keys.current_key()
    with pytest.raises(KeyError):
        keys.verification_key("unknown")
    with pytest.raises(KeyError):
        keys.verification_key(None)


def test_key_ring_rejects_a_previous_key_equal_to_the_current() -> None:
    with pytest.raises(ValueError, match="differ"):
        ring(previous=TEST_JWT_SECRET)


# JWT.


def test_jwt_round_trip_carries_the_documented_claims() -> None:
    clock = FixedClock(NOW)
    service = jwt_service(clock)

    issued = service.issue(GRANT)
    claims = service.decode(issued.token)

    assert issued.expires_at == NOW + timedelta(minutes=15)
    assert claims.user_id == USER
    assert claims.role is Role.DOCTOR
    assert claims.token_version == 3
    assert claims.amr == ("pwd", "otp")
    assert claims.session_id == GRANT.session_id
    payload = jwt.decode(issued.token, options={"verify_signature": False})
    assert set(payload) == {
        "iss", "aud", "sub", "role", "clinic_id", "tv", "sid", "amr", "jti",
        "iat", "nbf", "exp",
    }  # fmt: skip
    assert "permissions" not in payload
    assert jwt.get_unverified_header(issued.token)["kid"] == ring().current_key_id


def test_jwt_without_clinic_or_session_keeps_null_claims() -> None:
    service = jwt_service(FixedClock(NOW))
    grant = AccessGrant(
        user_id=USER,
        role=Role.PLATFORM_ADMIN,
        clinic_id=None,
        token_version=0,
        session_id=None,
        amr=("pwd",),
    )

    claims = service.decode(service.issue(grant).token)

    assert claims.clinic_id is None
    assert claims.session_id is None


def test_jwt_expiry_uses_the_injected_clock_with_leeway() -> None:
    clock = FixedClock(NOW)
    service = jwt_service(clock)
    token = service.issue(GRANT).token

    clock.advance(timedelta(minutes=15, seconds=29))
    service.decode(token)
    clock.advance(timedelta(seconds=1))
    with pytest.raises(UnauthenticatedError):
        service.decode(token)


def test_jwt_from_the_future_is_refused() -> None:
    clock = FixedClock(NOW)
    token = jwt_service(clock).issue(GRANT).token
    clock.advance(-timedelta(minutes=5))

    with pytest.raises(UnauthenticatedError):
        jwt_service(clock).decode(token)


def test_jwt_signed_with_the_previous_key_still_verifies_but_a_retired_one_not() -> (
    None
):
    clock = FixedClock(NOW)
    old_token = jwt_service(clock, ring(TEST_JWT_SECRET_PREVIOUS)).issue(GRANT).token

    rotated = jwt_service(clock, ring(TEST_JWT_SECRET, TEST_JWT_SECRET_PREVIOUS))
    assert rotated.decode(old_token).user_id == USER
    with pytest.raises(UnauthenticatedError):
        jwt_service(clock).decode(old_token)


def forged(**overrides: object) -> str:
    claims: dict[str, object] = {
        "iss": "insumap-api",
        "aud": "insumap-web",
        "sub": str(USER),
        "role": "DOCTOR",
        "clinic_id": None,
        "tv": 0,
        "sid": None,
        "amr": ["pwd"],
        "jti": "x",
        "iat": int(NOW.timestamp()),
        "nbf": int(NOW.timestamp()),
        "exp": int(NOW.timestamp()) + 600,
    }
    claims.update(overrides)
    keys = ring()
    return jwt.encode(
        claims,
        keys.current_key(),
        algorithm="HS256",
        headers={"kid": keys.current_key_id},
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "other"},
        {"aud": "other"},
        {"role": "ROOT"},
        {"tv": "0"},
        {"amr": "pwd"},
        {"sub": "not-a-uuid"},
        {"exp": "soon"},
    ],
)
def test_jwt_with_bad_claims_is_unauthenticated(overrides: dict[str, object]) -> None:
    with pytest.raises(UnauthenticatedError):
        jwt_service(FixedClock(NOW)).decode(forged(**overrides))


def test_jwt_missing_a_required_claim_or_with_other_algorithms_is_refused() -> None:
    service = jwt_service(FixedClock(NOW))
    keys = ring()
    incomplete = jwt.encode(
        {"sub": str(USER)}, keys.current_key(), "HS256",
        headers={"kid": keys.current_key_id},
    )  # fmt: skip
    unsigned = jwt.encode({"sub": "x"}, key=None, algorithm="none")  # type: ignore[arg-type]
    other_algorithm = jwt.encode(
        {"sub": "x"}, keys.current_key() * 2, "HS512",
        headers={"kid": keys.current_key_id},
    )  # fmt: skip
    for token in (incomplete, unsigned, other_algorithm, "garbage", ""):
        with pytest.raises(UnauthenticatedError):
            service.decode(token)


# Argon2id.


def hasher(**changes: int) -> Argon2PasswordHasher:
    values = {"memory_kib": 8, "time_cost": 1, "parallelism": 1, "max_concurrency": 2}
    values.update(changes)
    return Argon2PasswordHasher(PasswordHashingConfig(**values))


def test_argon2id_hashes_and_verifies_the_nfkc_form() -> None:
    password_hasher = hasher()

    stored = password_hasher.hash(
        "\uff43\uff4f\uff52\uff52\uff45\uff43\uff54 horse battery"
    )

    assert stored.startswith("$argon2id$")
    assert password_hasher.verify(stored, "correct horse battery")
    assert not password_hasher.verify(stored, "wrong")
    assert not password_hasher.verify("not-a-hash", "wrong")


def test_needs_rehash_when_parameters_change_or_the_hash_is_garbage() -> None:
    stored = hasher().hash("correct horse battery")

    assert not hasher().needs_rehash(stored)
    assert hasher(time_cost=2).needs_rehash(stored)
    assert hasher().needs_rehash("garbage")


def test_production_argon2_parameters_meet_the_owasp_minimum() -> None:
    fields = Settings.model_fields
    assert fields["argon2_memory_kib"].default >= 19456
    assert fields["argon2_time_cost"].default >= 2
    production = hasher(memory_kib=19456, time_cost=2)
    assert production.verify(
        production.hash("a long enough password"), "a long enough password"
    )


# Opaque tokens, recovery codes, ids.


def test_opaque_tokens_are_random_and_hashed_with_sha256() -> None:
    tokens = Sha256OpaqueTokens()

    first, second = tokens.new_token(), tokens.new_token()

    assert first.plain != second.plain
    assert len(first.token_hash) == 64
    assert tokens.hash(first.plain) == first.token_hash
    assert first.plain not in first.token_hash
    assert len(first.plain) <= 64


def test_recovery_codes_are_distinct_crockford_codes() -> None:
    codes = CrockfordRecoveryCodeGenerator().generate(10)

    assert len({code.value for code in codes}) == 10
    assert all(len(code.value) == 10 for code in codes)
    assert all("-" in code.formatted() for code in codes)


def test_uuid7_is_versioned_ordered_and_from_the_clock() -> None:
    clock = FixedClock(NOW)
    generator = Uuid7Generator(clock)

    first = generator.new_id()
    clock.advance(timedelta(seconds=1))
    second = generator.new_id()

    assert first.version == 7
    assert first.variant == uuid.RFC_4122
    assert first.int >> 80 == int(NOW.timestamp() * 1000)
    assert first < second


# TOTP.


def test_totp_accepts_the_window_and_refuses_replays() -> None:
    totp = PyOtpTotp(valid_window=1)
    secret = totp.new_secret()
    assert len(secret) == 32
    reference = pyotp.TOTP(secret)
    step = int(NOW.timestamp()) // 30

    current = reference.at(step * 30)
    assert totp.verify(secret, current, now=NOW, last_used_step=None) == step
    assert (
        totp.verify(secret, reference.at((step - 1) * 30), now=NOW, last_used_step=None)
        == step - 1
    )
    assert (
        totp.verify(secret, reference.at((step + 1) * 30), now=NOW, last_used_step=None)
        == step + 1
    )
    assert (
        totp.verify(secret, reference.at((step + 2) * 30), now=NOW, last_used_step=None)
        is None
    )
    assert totp.verify(secret, current, now=NOW, last_used_step=step) is None
    assert totp.verify(secret, "000000", now=NOW, last_used_step=None) in (None, step)


def test_totp_provisioning_uri_names_the_issuer() -> None:
    totp = PyOtpTotp(valid_window=1)

    uri = totp.provisioning_uri(totp.new_secret(), "medico@example.test")

    assert uri.startswith("otpauth://totp/Insumap:medico%40example.test?secret=")
    assert "issuer=Insumap" in uri


# AES-GCM and code HMAC.


def test_cipher_round_trip_is_bound_to_its_row() -> None:
    cipher = AesGcmSecretCipher(ring(TEST_CODE_HMAC_KEY))

    sealed = cipher.encrypt("JBSWY3DPEHPK3PXP", associated_data="row-1")

    assert b"JBSWY3DPEHPK3PXP" not in sealed.ciphertext
    assert cipher.decrypt(sealed, associated_data="row-1") == "JBSWY3DPEHPK3PXP"
    with pytest.raises(SecretDecryptionError):
        cipher.decrypt(sealed, associated_data="row-2")
    tampered = EncryptedSecret(
        ciphertext=sealed.ciphertext[:-1] + b"\x00", key_id=sealed.key_id
    )
    with pytest.raises(SecretDecryptionError):
        cipher.decrypt(tampered, associated_data="row-1")
    with pytest.raises(SecretDecryptionError):
        cipher.decrypt(
            EncryptedSecret(ciphertext=b"short", key_id="x"), associated_data="row-1"
        )


def test_cipher_decrypts_with_the_previous_key_but_not_a_retired_one() -> None:
    old = AesGcmSecretCipher(ring(TEST_JWT_SECRET_PREVIOUS))
    sealed = old.encrypt("secret", associated_data="a")

    rotated = AesGcmSecretCipher(ring(TEST_JWT_SECRET, TEST_JWT_SECRET_PREVIOUS))
    assert rotated.decrypt(sealed, associated_data="a") == "secret"
    with pytest.raises(SecretDecryptionError):
        AesGcmSecretCipher(ring(TEST_JWT_SECRET)).decrypt(sealed, associated_data="a")


def test_code_hasher_separates_purposes_and_rotates() -> None:
    previous = ring(TEST_JWT_SECRET_PREVIOUS)
    old = HmacCodeHasher(previous)
    rotated = HmacCodeHasher(ring(TEST_JWT_SECRET, TEST_JWT_SECRET_PREVIOUS))

    stored = old.hash_for_storage(CodePurpose.ACTIVATION, "ABCDEFGHJKMNPQRS")
    lookup = rotated.hashes_for_lookup(CodePurpose.ACTIVATION, "ABCDEFGHJKMNPQRS")

    assert len(stored.value) == 64
    assert stored.value in lookup
    assert lookup[0] != stored.value
    assert (
        stored.value
        != old.hash_for_storage(CodePurpose.RECOVERY, "ABCDEFGHJKMNPQRS").value
    )
    assert stored.key_id == previous.current_key_id


# Rate limiter.


def test_in_memory_rate_limiter_counts_per_subject_and_resets_with_the_window() -> None:
    clock = FixedClock(NOW)
    limiter = InMemoryRateLimiter(clock)
    rule = RateLimitRule(family="login", limit=2, window=timedelta(minutes=1))

    assert limiter.hit(rule, "a").allowed
    assert limiter.hit(rule, "a").allowed
    clock.advance(timedelta(seconds=20))
    blocked = limiter.hit(rule, "a")
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 40
    assert limiter.hit(rule, "b").allowed
    clock.advance(timedelta(seconds=40))
    assert limiter.hit(rule, "a").allowed


def test_test_keys_are_valid_base64() -> None:
    assert len(base64.b64decode(TEST_JWT_SECRET)) == 32
