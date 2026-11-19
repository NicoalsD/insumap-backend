"""Audit endpoints over PostgreSQL 18: scope, RLS, the hash chain and tampering."""

from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from insumap.infrastructure.security.password_hasher import (
    Argon2PasswordHasher,
    PasswordHashingConfig,
)
from tests.support.db_seed import ADMIN_EMAIL, DEMO_PASSWORD, DemoWorld
from tests.support.settings import make_settings

pytestmark = pytest.mark.integration

AUDIT_LOG = "/api/v1/audit-log"
DATA_ACCESS = "/api/v1/audit-log/data-access"
VERIFY = "/api/v1/audit-log/verifications"
EVENTS = "/api/v1/security-events"
PLATFORM_EMAIL = "auditoria.plataforma@example.test"
PLACEHOLDER_HASH = "0" * 64
REASON = "Emisión de credenciales de prueba de auditoría"
TAMPER_REASON = "Motivo alterado directamente en la base de datos"
TRIGGER = "trg_audit_log_append_only"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _staff_token(api: TestClient, email: str) -> str:
    """Enroll MFA, then sign in with a recovery code (a TOTP step cannot repeat)."""
    first = api.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert first.json()["status"] == "MFA_ENROLLMENT_REQUIRED", first.text
    headers = _bearer(first.json()["access_token"])
    started = api.post("/api/v1/auth/mfa/enrollment", headers=headers)
    secret = parse_qs(urlsplit(started.json()["otpauth_uri"]).query)["secret"][0]
    confirmed = api.post(
        "/api/v1/auth/mfa/enrollment/confirm",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert confirmed.status_code == 200, confirmed.text
    challenge = api.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    verified = api.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge_token": challenge.json()["challenge_token"],
            "code": confirmed.json()["recovery_codes"][0],
        },
    )
    assert verified.status_code == 200, verified.text
    return str(verified.json()["access_token"])


@pytest.fixture
def admin(api: TestClient) -> dict[str, str]:
    return _bearer(_staff_token(api, ADMIN_EMAIL))


@pytest.fixture
def platform_admin(api: TestClient, migrated_url: str) -> dict[str, str]:
    """A platform administrator: a membership with no clinic (API.md 8.3)."""
    settings = make_settings()
    hasher = Argon2PasswordHasher(
        PasswordHashingConfig(
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
            max_concurrency=settings.password_hash_max_concurrency,
        )
    )
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        user = conn.execute(
            "INSERT INTO iam.users (email, email_normalized, password_hash, status)"
            " VALUES (%s, %s, %s, 'ACTIVE') RETURNING id",
            (PLATFORM_EMAIL, PLATFORM_EMAIL, hasher.hash(DEMO_PASSWORD)),
        ).fetchone()
        assert user is not None
        conn.execute(
            "INSERT INTO iam.memberships (user_id, clinic_id, role_id)"
            " SELECT %s, NULL, id FROM iam.roles WHERE code = 'PLATFORM_ADMIN'",
            (user[0],),
        )
    return _bearer(_staff_token(api, PLATFORM_EMAIL))


def _seed_clinic_actions(url: str, demo: DemoWorld, count: int) -> list[UUID]:
    """Insert actions as the superuser: the trigger computes the chain itself."""
    ids: list[UUID] = []
    with psycopg.connect(url, autocommit=True) as conn:
        for _ in range(count):
            row = conn.execute(
                "INSERT INTO audit.audit_log (clinic_id, chain_seq, actor_user_id,"
                " actor_role, actor_type, action, entity_type, reason,"
                " changed_fields, prev_hash, row_hash)"
                " VALUES (%s, 1, %s, 'CLINIC_ADMIN', 'USER', 'CREDENTIALS_ISSUED',"
                " 'PATIENT', %s, ARRAY['status'], %s, %s) RETURNING id",
                (
                    demo.clinic_id,
                    demo.admin_user_id,
                    REASON,
                    PLACEHOLDER_HASH,
                    PLACEHOLDER_HASH,
                ),
            ).fetchone()
            assert row is not None
            ids.append(row[0])
    return ids


def _tamper(url: str, row_id: UUID) -> None:
    """Change a row as the superuser, with the append-only guard off for the change.

    The row keeps its stored hashes, so the recomputed content no longer matches.
    """
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"ALTER TABLE audit.audit_log DISABLE TRIGGER {TRIGGER}")
        try:
            conn.execute(
                "UPDATE audit.audit_log SET reason = %s WHERE id = %s",
                (TAMPER_REASON, row_id),
            )
        finally:
            conn.execute(f"ALTER TABLE audit.audit_log ENABLE TRIGGER {TRIGGER}")


def _superuser_rows(
    url: str, sql: str, params: tuple[Any, ...]
) -> list[tuple[Any, ...]]:
    with psycopg.connect(url) as conn:
        return list(conn.execute(sql, params).fetchall())


def test_clinic_admin_reads_only_the_clinic_audit_log(
    api: TestClient, admin: dict[str, str], migrated_url: str, demo_world: DemoWorld
) -> None:
    _seed_clinic_actions(migrated_url, demo_world, 2)

    response = api.get(AUDIT_LOG, headers=admin, params={"limit": 10})

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 2
    assert {item["action"] for item in body["items"]} == {"CREDENTIALS_ISSUED"}
    assert all(item["changed_fields"] == ["status"] for item in body["items"])
    assert all(item["reason"] == REASON for item in body["items"])


def test_audit_log_pages_with_a_cursor(
    api: TestClient, admin: dict[str, str], migrated_url: str, demo_world: DemoWorld
) -> None:
    _seed_clinic_actions(migrated_url, demo_world, 3)

    first = api.get(AUDIT_LOG, headers=admin, params={"limit": 2}).json()
    second = api.get(
        AUDIT_LOG,
        headers=admin,
        params={"limit": 2, "cursor": first["next_cursor"]},
    ).json()

    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None
    assert len(second["items"]) == 1
    assert second["next_cursor"] is None
    seen = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(seen)) == 3


def test_an_intact_chain_verifies(
    api: TestClient, admin: dict[str, str], migrated_url: str, demo_world: DemoWorld
) -> None:
    _seed_clinic_actions(migrated_url, demo_world, 3)

    response = api.post(VERIFY, headers=admin)

    assert response.status_code == 200, response.text
    assert response.json() == {"is_valid": True, "first_inconsistent_row_id": None}


def test_a_tampered_chain_is_reported_and_recorded(
    api: TestClient, admin: dict[str, str], migrated_url: str, demo_world: DemoWorld
) -> None:
    ids = _seed_clinic_actions(migrated_url, demo_world, 3)
    _tamper(migrated_url, ids[1])

    response = api.post(VERIFY, headers=admin)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "is_valid": False,
        "first_inconsistent_row_id": str(ids[1]),
    }
    recorded = _superuser_rows(
        migrated_url,
        "SELECT severity, clinic_id FROM iam.security_events"
        " WHERE event_type = 'AUDIT_CHAIN_BROKEN' AND clinic_id = %s",
        (demo_world.clinic_id,),
    )
    assert recorded == [("CRITICAL", demo_world.clinic_id)]


def test_the_tampered_event_is_listed_for_the_clinic(
    api: TestClient, admin: dict[str, str], migrated_url: str, demo_world: DemoWorld
) -> None:
    ids = _seed_clinic_actions(migrated_url, demo_world, 2)
    _tamper(migrated_url, ids[0])
    api.post(VERIFY, headers=admin)

    response = api.get(
        EVENTS,
        headers=admin,
        params={"type": "AUDIT_CHAIN_BROKEN", "severity": "CRITICAL"},
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "AUDIT_CHAIN_BROKEN"
    assert items[0]["clinic_id"] == str(demo_world.clinic_id)


def test_clinic_admin_does_not_see_platform_events(
    api: TestClient,
    admin: dict[str, str],
    migrated_url: str,
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO iam.security_events (event_type, severity, clinic_id)"
            " VALUES ('LOGIN_FAILED', 'LOW', NULL)"
        )

    response = api.get(EVENTS, headers=admin)

    assert response.status_code == 200, response.text
    assert all(item["clinic_id"] is not None for item in response.json()["items"])


def test_platform_admin_sees_platform_events(
    api: TestClient,
    platform_admin: dict[str, str],
    migrated_url: str,
) -> None:
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO iam.security_events (event_type, severity, clinic_id)"
            " VALUES ('SECRET_ROTATED', 'LOW', NULL)"
        )

    response = api.get(
        EVENTS, headers=platform_admin, params={"type": "SECRET_ROTATED"}
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    assert all(item["clinic_id"] is None for item in items)


def test_platform_admin_has_no_clinic_audit_log(
    api: TestClient, platform_admin: dict[str, str]
) -> None:
    response = api.get(AUDIT_LOG, headers=platform_admin)

    assert response.status_code == 403, response.text
