"""Staff endpoints over PostgreSQL 18: the real schema, RLS and the audit trail."""

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.support.db_seed import (
    ADMIN_EMAIL,
    DEMO_PASSWORD,
    DOCTOR_EMAIL,
    DemoWorld,
)
from tests.support.notifications import InMemoryChannel

pytestmark = pytest.mark.integration

BASE = "/api/v1/users"
CURRENT_USER = "/api/v1/auth/current-user"
REFRESH_PATH = "/api/v1/auth"
REFRESH_COOKIE = "__Secure-insumap_rt"
CSRF = {"X-Requested-With": "insumap-web"}
REASON = "Salida de la clínica del personal"
NEW_DOCTOR_EMAIL = "nueva.medica@example.test"
LICENSE = "RM-1001"
CODE_PATTERN = re.compile(r"[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _enroll(api: TestClient, email: str) -> str:
    """Sign in a demo staff member, enrolling its MFA; returns its full access token.

    The refresh cookie of that session stays in the client's jar.
    """
    first = api.post(
        "/api/v1/auth/login",
        json={"email": email, "password": DEMO_PASSWORD},
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
    return str(confirmed.json()["access_token"])


def _admin_token(api: TestClient) -> str:
    return _enroll(api, ADMIN_EMAIL)


def _new_doctor(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": NEW_DOCTOR_EMAIL,
        "full_name": "Nueva Médica de Prueba",
        "role": "DOCTOR",
        "professional_license": LICENSE,
        "specialty": "Endocrinología",
    }
    body.update(overrides)
    return body


def _one(url: str, sql: str, params: tuple[object, ...]) -> tuple[Any, ...]:
    """A superuser read: it bypasses row level security, to check what was written."""
    with psycopg.connect(url) as conn:
        row = conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def _outside_doctor(url: str) -> str:
    """A doctor of another clinic, inserted with the superuser."""
    with psycopg.connect(url, autocommit=True) as conn:
        clinic_id = conn.execute(
            "INSERT INTO clinic.clinics (name, tax_id, timezone, is_demo)"
            " VALUES ('Clínica Ajena de Prueba', '900000002-3',"
            " 'America/Bogota', false)"
            " RETURNING id"
        ).fetchone()
        assert clinic_id is not None
        user_id = conn.execute(
            "INSERT INTO iam.users (email, email_normalized, status)"
            " VALUES ('ajena@example.test', 'ajena@example.test', 'ACTIVE')"
            " RETURNING id"
        ).fetchone()
        assert user_id is not None
        conn.execute(
            "INSERT INTO iam.memberships (user_id, clinic_id, role_id)"
            " SELECT %s, %s, id FROM iam.roles WHERE code = 'DOCTOR'",
            (user_id[0], clinic_id[0]),
        )
        conn.execute(
            "INSERT INTO clinic.staff_profiles (user_id, clinic_id, full_name,"
            " professional_license) VALUES (%s, %s, 'Médica Ajena', 'RM-9999')",
            (user_id[0], clinic_id[0]),
        )
    return str(user_id[0])


def test_staff_lifecycle_over_the_real_schema(
    api: TestClient, demo_world: DemoWorld, mail: InMemoryChannel, migrated_url: str
) -> None:
    headers = _bearer(_admin_token(api))

    created = api.post(BASE, headers=headers, json=_new_doctor())

    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    assert created.json()["is_active"] is False
    [sent] = mail.delivered
    assert CODE_PATTERN.search(sent.body), "the activation code travels by email"
    assert CODE_PATTERN.search(created.text) is None
    status, status_reason = _one(
        migrated_url,
        "SELECT status, status_reason FROM iam.users WHERE id = %s",
        (user_id,),
    )
    assert (status, status_reason) == ("INVITED", None)
    clinic_id, is_active = _one(
        migrated_url,
        "SELECT clinic_id, is_active FROM iam.memberships WHERE user_id = %s",
        (user_id,),
    )
    assert (clinic_id, is_active) == (demo_world.clinic_id, True)
    invitation = _one(
        migrated_url,
        "SELECT purpose, channel, status, delivery_status"
        " FROM iam.credential_invitations WHERE user_id = %s",
        (user_id,),
    )
    assert invitation == ("STAFF_ACTIVATION", "EMAIL", "PENDING", "PENDING")

    listing = api.get(BASE, headers=headers, params={"role": "DOCTOR"})
    assert user_id in {item["id"] for item in listing.json()["items"]}
    detail = api.get(f"{BASE}/{user_id}", headers=headers)
    assert detail.json()["professional_license"] == LICENSE
    patched = api.patch(
        f"{BASE}/{user_id}", headers=headers, json={"specialty": "Medicina interna"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["specialty"] == "Medicina interna"

    same_license = api.post(
        BASE,
        headers=headers,
        json=_new_doctor(email="otra.medica@example.test"),
    )
    same_email = api.post(BASE, headers=headers, json=_new_doctor())
    assert same_license.status_code == 409, same_license.text
    assert same_email.status_code == 409, same_email.text

    closed = api.post(
        f"{BASE}/{user_id}/deactivate", headers=headers, json={"reason": REASON}
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["is_active"] is False
    assert _one(
        migrated_url,
        "SELECT status, status_reason, token_version FROM iam.users WHERE id = %s",
        (user_id,),
    ) == ("DEACTIVATED", REASON, 1)
    assert _one(
        migrated_url,
        "SELECT is_active, ended_at IS NOT NULL"
        " FROM iam.memberships WHERE user_id = %s",
        (user_id,),
    ) == (False, True)

    unlocked = api.post(f"{BASE}/{user_id}/unlock", headers=headers)
    reset = api.post(
        f"{BASE}/{demo_world.doctor_user_id}/mfa-reset",
        headers=headers,
        json={"reason": REASON},
    )
    assert unlocked.status_code == 204, unlocked.text
    assert reset.status_code == 204, reset.text

    with psycopg.connect(migrated_url) as conn:
        actions = {
            row[0]
            for row in conn.execute(
                "SELECT action FROM audit.audit_log WHERE entity_id = %s", (user_id,)
            )
        }
    assert {"USER_CREATED", "USER_UPDATED", "USER_DEACTIVATED"} <= actions


def test_another_clinics_staff_is_the_same_404_as_a_missing_one(
    api: TestClient, migrated_url: str
) -> None:
    headers = _bearer(_admin_token(api))
    outsider = _outside_doctor(migrated_url)

    found_elsewhere = api.get(f"{BASE}/{outsider}", headers=headers)
    missing = api.get(f"{BASE}/{uuid4()}", headers=headers)

    assert found_elsewhere.status_code == missing.status_code == 404
    assert found_elsewhere.json() == missing.json()


def _revoked_refresh(api: TestClient, cookie: str) -> Any:
    """Present an old refresh cookie alone, as a browser does after a session ends."""
    api.cookies.clear()
    api.cookies.set(REFRESH_COOKIE, cookie, path=REFRESH_PATH)
    return api.post("/api/v1/auth/refresh", headers=CSRF)


def test_mfa_reset_ends_the_sessions_and_forces_enrollment(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    doctor_token = _enroll(api, DOCTOR_EMAIL)
    doctor_refresh = api.cookies.get(REFRESH_COOKIE, path=REFRESH_PATH)
    assert doctor_refresh
    assert api.get(CURRENT_USER, headers=_bearer(doctor_token)).status_code == 200
    admin_headers = _bearer(_admin_token(api))

    reset = api.post(
        f"{BASE}/{demo_world.doctor_user_id}/mfa-reset",
        headers=admin_headers,
        json={"reason": REASON},
    )

    assert reset.status_code == 204, reset.text
    stale = api.get(CURRENT_USER, headers=_bearer(doctor_token))
    assert stale.status_code == 401, stale.text
    assert stale.json()["error"]["code"] == "SESSION_REVOKED"
    old_refresh = _revoked_refresh(api, doctor_refresh)
    assert old_refresh.status_code == 401, old_refresh.text
    api.cookies.clear()
    login = api.post(
        "/api/v1/auth/login",
        json={"email": DOCTOR_EMAIL, "password": DEMO_PASSWORD},
    )
    assert login.json()["status"] == "MFA_ENROLLMENT_REQUIRED", login.text
    doctor = str(demo_world.doctor_user_id)
    assert _one(
        migrated_url,
        "SELECT revoked_at IS NOT NULL FROM iam.mfa_factors"
        " WHERE user_id = %s AND factor_type = 'TOTP'",
        (doctor,),
    ) == (True,)
    assert _one(
        migrated_url,
        "SELECT count(*) FROM iam.refresh_tokens WHERE user_id = %s"
        " AND revoked_at IS NULL",
        (doctor,),
    ) == (0,)


def test_deactivation_ends_the_sessions_and_blocks_sign_in(
    api: TestClient, demo_world: DemoWorld
) -> None:
    doctor_token = _enroll(api, DOCTOR_EMAIL)
    doctor_refresh = api.cookies.get(REFRESH_COOKIE, path=REFRESH_PATH)
    assert doctor_refresh
    admin_headers = _bearer(_admin_token(api))

    closed = api.post(
        f"{BASE}/{demo_world.doctor_user_id}/deactivate",
        headers=admin_headers,
        json={"reason": REASON},
    )

    assert closed.status_code == 200, closed.text
    stale = api.get(CURRENT_USER, headers=_bearer(doctor_token))
    assert stale.status_code == 401, stale.text
    assert stale.json()["error"]["code"] == "SESSION_REVOKED"
    assert _revoked_refresh(api, doctor_refresh).status_code == 401
    api.cookies.clear()
    login = api.post(
        "/api/v1/auth/login",
        json={"email": DOCTOR_EMAIL, "password": DEMO_PASSWORD},
    )
    assert login.status_code == 403, login.text
    assert login.json()["error"]["code"] == "ACCOUNT_NOT_ACTIVE"
