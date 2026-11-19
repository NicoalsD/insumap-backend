"""Clinic endpoints over PostgreSQL 18: unique index, suspension trigger and RLS."""

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
from tests.support.db_seed import (
    ADMIN_EMAIL,
    DEMO_CLINIC_NAME,
    DEMO_PASSWORD,
    PATIENT_EMAIL,
    DemoWorld,
)
from tests.support.settings import make_settings

pytestmark = pytest.mark.integration

BASE = "/api/v1/clinics"
PLATFORM_EMAIL = "plataforma.demo@example.test"
REASON = "Revisión de contrato con la clínica"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(api: TestClient, email: str) -> Any:
    return api.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )


def _staff_token(api: TestClient, email: str) -> str:
    """Enroll MFA, then sign in with a recovery code (a TOTP step cannot repeat)."""
    first = _login(api, email)
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
    challenge = _login(api, email)
    assert challenge.json()["status"] == "MFA_CHALLENGE", challenge.text
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
def platform_email(migrated_url: str, demo_world: DemoWorld) -> str:
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
        user_id = conn.execute(
            "INSERT INTO iam.users (email, email_normalized, password_hash, status)"
            " VALUES (%s, %s, %s, 'ACTIVE') RETURNING id",
            (PLATFORM_EMAIL, PLATFORM_EMAIL, hasher.hash(DEMO_PASSWORD)),
        ).fetchone()
        assert user_id is not None
        conn.execute(
            "INSERT INTO iam.memberships (user_id, clinic_id, role_id)"
            " SELECT %s, NULL, id FROM iam.roles WHERE code = 'PLATFORM_ADMIN'",
            (user_id[0],),
        )
    return PLATFORM_EMAIL


@pytest.fixture
def platform(api: TestClient, platform_email: str) -> dict[str, str]:
    return _bearer(_staff_token(api, platform_email))


def _audit_actions(url: str, clinic_id: str) -> list[str]:
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "SELECT action FROM audit.audit_log"
            " WHERE clinic_id = %s ORDER BY chain_seq",
            (UUID(clinic_id),),
        ).fetchall()
    return [row[0] for row in rows]


def _open_refresh_tokens(url: str, clinic_id: UUID) -> int:
    with psycopg.connect(url) as conn:
        count = conn.execute(
            "SELECT count(*) FROM iam.refresh_tokens"
            " WHERE clinic_id = %s AND revoked_at IS NULL",
            (clinic_id,),
        ).fetchone()
    assert count is not None
    return int(count[0])


def test_platform_admin_creates_lists_and_reads_a_clinic(
    api: TestClient, platform: dict[str, str], migrated_url: str
) -> None:
    created = api.post(
        BASE,
        headers=platform,
        json={"name": "Clínica Norte", "tax_id": "900000001"},
    )

    assert created.status_code == 201, created.text
    clinic_id = created.json()["id"]
    assert created.json()["timezone"] == "America/Bogota"
    listed = api.get(BASE, headers=platform, params={"limit": 10})
    names = {item["name"] for item in listed.json()["items"]}
    assert {DEMO_CLINIC_NAME, "Clínica Norte"} <= names
    read = api.get(f"{BASE}/{clinic_id}", headers=platform)
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "ACTIVE"
    assert _audit_actions(migrated_url, clinic_id) == ["CLINIC_CREATED"]


def test_a_repeated_name_is_409_from_the_unique_index(
    api: TestClient, platform: dict[str, str]
) -> None:
    response = api.post(
        BASE,
        headers=platform,
        json={"name": DEMO_CLINIC_NAME.upper(), "tax_id": "900000002"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"


def test_suspension_revokes_the_sessions_and_blocks_sign_in(
    api: TestClient,
    platform: dict[str, str],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    assert _login(api, PATIENT_EMAIL).status_code == 200
    assert _open_refresh_tokens(migrated_url, demo_world.clinic_id) > 0

    suspended = api.post(
        f"{BASE}/{demo_world.clinic_id}/suspend",
        headers=platform,
        json={"reason": REASON},
    )

    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "SUSPENDED"
    assert _open_refresh_tokens(migrated_url, demo_world.clinic_id) == 0
    blocked = _login(api, PATIENT_EMAIL)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["code"] == "CLINIC_SUSPENDED"
    assert _audit_actions(migrated_url, str(demo_world.clinic_id)) == [
        "CLINIC_SUSPENDED"
    ]


def test_reactivation_lets_the_clinic_sign_in_again(
    api: TestClient,
    platform: dict[str, str],
    demo_world: DemoWorld,
) -> None:
    url = f"{BASE}/{demo_world.clinic_id}"
    api.post(f"{url}/suspend", headers=platform, json={"reason": REASON})

    reactivated = api.post(f"{url}/reactivate", headers=platform)

    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "ACTIVE"
    assert _login(api, PATIENT_EMAIL).status_code == 200


def test_clinic_admin_reads_its_own_clinic_and_cannot_list(
    api: TestClient, demo_world: DemoWorld
) -> None:
    headers = _bearer(_staff_token(api, ADMIN_EMAIL))

    current = api.get(f"{BASE}/current", headers=headers)
    listed = api.get(BASE, headers=headers)

    assert current.status_code == 200, current.text
    assert current.json()["id"] == str(demo_world.clinic_id)
    assert current.json()["simulated"] is True
    assert listed.status_code == 403


def test_rls_shows_a_clinic_admin_only_its_own_clinic(
    app_url: str, demo_world: DemoWorld, migrated_url: str
) -> None:
    other = UUID("00000000-0000-7000-8000-00000000c0de")
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO clinic.clinics (id, name, tax_id, timezone)"
            " VALUES (%s, 'Clínica Ajena', '900000003', 'America/Bogota')",
            (other,),
        )

    with psycopg.connect(app_url) as conn:
        conn.execute(
            "SELECT set_config('app.clinic_id', %s, true),"
            " set_config('app.user_id', %s, true),"
            " set_config('app.role', 'CLINIC_ADMIN', true)",
            (str(demo_world.clinic_id), str(demo_world.admin_user_id)),
        )
        visible = [
            row[0] for row in conn.execute("SELECT id FROM clinic.clinics").fetchall()
        ]

    assert visible == [demo_world.clinic_id]


def test_patch_writes_the_fields_and_bumps_the_lock_version(
    api: TestClient,
    platform: dict[str, str],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    response = api.patch(
        f"{BASE}/{demo_world.clinic_id}",
        headers=platform,
        json={"name": "Clínica Renovada", "timezone": "America/Lima", "is_demo": False},
    )

    assert response.status_code == 200, response.text
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT name, timezone, is_demo, lock_version, updated_at > created_at"
            " FROM clinic.clinics WHERE id = %s",
            (demo_world.clinic_id,),
        ).fetchone()
    assert row == ("Clínica Renovada", "America/Lima", False, 1, True)
