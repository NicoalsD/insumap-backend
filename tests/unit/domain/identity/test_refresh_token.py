from datetime import UTC, datetime, timedelta
from uuid import UUID

from insumap.domain.identity.refresh_token import (
    RefreshAssessment,
    RefreshToken,
    RefreshTokenLifetime,
    RevocationReason,
)

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
LIFETIME = RefreshTokenLifetime(token=timedelta(days=30), family=timedelta(days=90))


def first_token() -> RefreshToken:
    return RefreshToken.open_family(
        token_id=UUID(int=1),
        family_id=UUID(int=100),
        user_id=UUID(int=7),
        clinic_id=UUID(int=9),
        token_hash="a" * 64,
        now=NOW,
        lifetime=LIFETIME,
    )


def test_opening_a_family_sets_both_lifetimes() -> None:
    token = first_token()

    assert token.expires_at == NOW + timedelta(days=30)
    assert token.family_expires_at == NOW + timedelta(days=90)
    assert token.assess(NOW) is RefreshAssessment.VALID


def test_token_lifetime_never_exceeds_the_family() -> None:
    staff = RefreshTokenLifetime(token=timedelta(days=30), family=timedelta(hours=12))
    token = RefreshToken.open_family(
        token_id=UUID(int=1),
        family_id=UUID(int=2),
        user_id=UUID(int=3),
        clinic_id=None,
        token_hash="b" * 64,
        now=NOW,
        lifetime=staff,
    )

    assert token.expires_at == token.family_expires_at == NOW + timedelta(hours=12)


def test_successor_keeps_the_family_and_the_inactivity_window() -> None:
    later = NOW + timedelta(days=10)

    successor = first_token().successor(
        token_id=UUID(int=2), token_hash="c" * 64, now=later
    )

    assert successor.family_id == UUID(int=100)
    assert successor.issued_at == later
    assert successor.expires_at == later + timedelta(days=30)
    assert successor.revoked_at is None


def test_successor_is_cut_at_the_end_of_the_family() -> None:
    late = NOW + timedelta(days=80)

    successor = first_token().successor(
        token_id=UUID(int=2), token_hash="d" * 64, now=late
    )

    assert successor.expires_at == NOW + timedelta(days=90)


def test_expired_token_is_expired_not_reused() -> None:
    token = first_token()

    assert token.assess(NOW + timedelta(days=30)) is RefreshAssessment.EXPIRED


def test_family_end_expires_a_token() -> None:
    token = first_token()
    ended = NOW + timedelta(days=90)

    assert token.assess(ended) is RefreshAssessment.EXPIRED


def test_revoked_token_presented_again_is_reuse_even_after_expiry() -> None:
    rotated = first_token().revoked(reason=RevocationReason.ROTATED, now=NOW)

    assert rotated.is_revoked
    assert rotated.assess(NOW) is RefreshAssessment.REUSED
    assert rotated.assess(NOW + timedelta(days=365)) is RefreshAssessment.REUSED


def test_revoking_twice_keeps_the_first_reason() -> None:
    rotated = first_token().revoked(reason=RevocationReason.ROTATED, now=NOW)

    again = rotated.revoked(
        reason=RevocationReason.REUSE_DETECTED, now=NOW + timedelta(minutes=1)
    )

    assert again.revoked_reason is RevocationReason.ROTATED
    assert again.revoked_at == NOW
