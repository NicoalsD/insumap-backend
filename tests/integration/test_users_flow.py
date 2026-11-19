"""Staff endpoints over PostgreSQL 18: the real schema, RLS and the audit trail."""

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.support.db_seed import ADMIN_EMAIL, DEMO_PASSWORD, DemoWorld
from tests.support.notifications import InMemoryChannel

pytestmark = pytest.mark.integration

BASE = "/api/v1/users"
REASON = "Salida de la clínica del personal"
NEW_DOCTOR_EMAIL = "nueva.medica@example.test"
LICENSE = "RM-1001"
CODE_PATTERN = re.compile(r"[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _admin_token(api: TestClient) -> str:
    """Sign in the demo administrator, enrolling its MFA on the first sign-in."""
    first = api.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": DEMO_PASSWORD},
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
