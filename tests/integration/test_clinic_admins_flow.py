"""First clinic administrator over PostgreSQL: the definer function, RLS and audit."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from insumap.infrastructure.security.password_hasher import (
    Argon2PasswordHasher,
    PasswordHashingConfig,
)
from tests.integration.test_clinics_flow import _audit_actions, _bearer, _staff_token
from tests.support.db_seed import ADMIN_EMAIL, DEMO_PASSWORD, DemoWorld
from tests.support.notifications import InMemoryChannel
from tests.support.settings import make_settings

pytestmark = pytest.mark.integration

BASE = "/api/v1/clinics"
PLATFORM_EMAIL = "plataforma.admins@example.test"
EMAIL = "admin.norte@example.test"
ACTION = "CLINIC_ADMIN_CREATED"
REASON = "Revisión de contrato con la clínica"
FORMATTED_CODE = re.compile(r"\b[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}\b")


@pytest.fixture
def platform(
    api: TestClient, migrated_url: str, demo_world: DemoWorld
) -> dict[str, str]:
    """A platform administrator (a membership with no clinic) signed in with MFA."""
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


def _create(
    api: TestClient, headers: dict[str, str], clinic_id: UUID, email: str = EMAIL
) -> Any:
    return api.post(
        f"{BASE}/{clinic_id}/admins",
        headers=headers,
        json={"email": email, "full_name": "Ana Administradora"},
    )


def _accounts(url: str, email: str) -> list[tuple[Any, ...]]:
    """Rows as the superuser sees them: the check is on the database, not on RLS."""
    with psycopg.connect(url) as conn:
        return conn.execute(
            "SELECT u.id, u.status, m.clinic_id, r.code, sp.full_name"
            " FROM iam.users AS u"
            " JOIN iam.memberships AS m ON m.user_id = u.id"
            " JOIN iam.roles AS r ON r.id = m.role_id"
            " JOIN clinic.staff_profiles AS sp ON sp.user_id = u.id"
            " WHERE u.email_normalized = %s",
            (email,),
        ).fetchall()


def test_the_function_creates_an_invited_admin_with_a_hashed_code(
    api: TestClient,
    platform: dict[str, str],
    demo_world: DemoWorld,
    migrated_url: str,
    mail: InMemoryChannel,
) -> None:
    response = _create(api, platform, demo_world.clinic_id)

    assert response.status_code == 201, response.text
    user_id = response.json()["user_id"]
    [(row_id, status, clinic_id, role, full_name)] = _accounts(migrated_url, EMAIL)
    assert str(row_id) == user_id
    assert status == "INVITED"
    assert clinic_id == demo_world.clinic_id
    assert role == "CLINIC_ADMIN"
    assert full_name == "Ana Administradora"
    with psycopg.connect(migrated_url) as conn:
        invitation = conn.execute(
            "SELECT purpose, channel, status, code_hash, code_key_id, expires_at"
            " FROM iam.credential_invitations WHERE user_id = %s",
            (UUID(user_id),),
        ).fetchone()
    assert invitation is not None
    purpose, channel, invitation_status, code_hash, key_id, expires_at = invitation
    assert (purpose, channel, invitation_status) == (
        "STAFF_ACTIVATION",
        "EMAIL",
        "PENDING",
    )
    assert re.fullmatch(r"[0-9a-f]{64}", code_hash)
    assert len(key_id) == 16
    assert expires_at == datetime.fromisoformat(
        response.json()["invitation_expires_at"]
    )
    [delivered] = mail.delivered
    assert delivered.recipient.address == EMAIL
    assert FORMATTED_CODE.search(delivered.body) is not None
    assert code_hash not in delivered.body


def test_the_audit_row_lands_in_the_target_clinic_chain(
    api: TestClient,
    platform: dict[str, str],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    assert _create(api, platform, demo_world.clinic_id).status_code == 201

    assert _audit_actions(migrated_url, str(demo_world.clinic_id)) == [ACTION]


def test_a_repeated_email_is_409_and_leaves_one_account(
    api: TestClient,
    platform: dict[str, str],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    assert _create(api, platform, demo_world.clinic_id).status_code == 201

    response = _create(api, platform, demo_world.clinic_id, email=EMAIL.upper())

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"
    assert len(_accounts(migrated_url, EMAIL)) == 1


def test_a_suspended_clinic_is_409_and_writes_nothing(
    api: TestClient,
    platform: dict[str, str],
    migrated_url: str,
) -> None:
    created = api.post(
        BASE, headers=platform, json={"name": "Clínica Sur", "tax_id": "900000077"}
    )
    clinic_id = UUID(created.json()["id"])
    suspended = api.post(
        f"{BASE}/{clinic_id}/suspend", headers=platform, json={"reason": REASON}
    )
    assert suspended.status_code == 200, suspended.text

    response = _create(api, platform, clinic_id)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert _accounts(migrated_url, EMAIL) == []


def test_an_unknown_clinic_is_404(api: TestClient, platform: dict[str, str]) -> None:
    response = _create(api, platform, uuid4())

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_clinic_admin_cannot_create_another_admin(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    headers = _bearer(_staff_token(api, ADMIN_EMAIL))

    response = _create(api, headers, demo_world.clinic_id)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert _accounts(migrated_url, EMAIL) == []
