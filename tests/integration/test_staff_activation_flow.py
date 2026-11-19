"""Activation of invited staff over PostgreSQL 18: the real schema and RLS."""

from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_users_flow import (
    BASE,
    CODE_PATTERN,
    NEW_DOCTOR_EMAIL,
    _admin_token,
    _bearer,
    _new_doctor,
)
from tests.support.db_seed import DemoWorld
from tests.support.notifications import InMemoryChannel

pytestmark = pytest.mark.integration

AUTH = "/api/v1/auth"
STAFF_PASSWORD = "a long staff passphrase 2026"


def _one(url: str, sql: str, params: tuple[object, ...]) -> tuple[Any, ...]:
    """A superuser read: it bypasses row level security, to check what was written."""
    with psycopg.connect(url) as conn:
        row = conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def _emailed_code(mail: InMemoryChannel) -> str:
    match = CODE_PATTERN.search(mail.delivered[0].body)
    assert match is not None, "the activation code travels by email"
    return match.group(0)


def _activate(api: TestClient, code: str) -> dict[str, Any]:
    verified = api.post(f"{AUTH}/activation/verify", json={"activation_code": code})
    assert verified.status_code == 200, verified.text
    assert verified.json()["privacy_notice_version_id"] is None
    done = api.post(
        f"{AUTH}/activation/complete",
        json={
            "activation_token": verified.json()["activation_token"],
            "new_password": STAFF_PASSWORD,
        },
    )
    assert done.status_code == 200, done.text
    return dict(done.json())


def test_a_new_doctor_activates_with_the_emailed_code_and_enrolls_mfa(
    api: TestClient,
    demo_world: DemoWorld,
    mail: InMemoryChannel,
    migrated_url: str,
) -> None:
    created = api.post(BASE, headers=_bearer(_admin_token(api)), json=_new_doctor())
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    code = _emailed_code(mail)

    done = _activate(api, code)

    assert done["status"] == "MFA_ENROLLMENT_REQUIRED"
    assert _one(
        migrated_url, "SELECT status FROM iam.users WHERE id = %s", (user_id,)
    ) == ("ACTIVE",)
    assert _one(
        migrated_url,
        "SELECT status FROM iam.credential_invitations WHERE user_id = %s",
        (user_id,),
    ) == ("USED",)
    assert _one(
        migrated_url,
        "SELECT count(*) FROM clinic.patient_consents WHERE recorded_by = %s",
        (user_id,),
    ) == (0,)

    replay = api.post(f"{AUTH}/activation/verify", json={"activation_code": code})
    assert replay.status_code == 410, replay.text
    assert replay.json()["error"]["code"] == "INVITATION_INVALID"

    login = api.post(
        f"{AUTH}/login", json={"email": NEW_DOCTOR_EMAIL, "password": STAFF_PASSWORD}
    )
    assert login.json()["status"] == "MFA_ENROLLMENT_REQUIRED", login.text
    headers = _bearer(login.json()["access_token"])
    started = api.post(f"{AUTH}/mfa/enrollment", headers=headers)
    secret = parse_qs(urlsplit(started.json()["otpauth_uri"]).query)["secret"][0]
    confirmed = api.post(
        f"{AUTH}/mfa/enrollment/confirm",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert confirmed.status_code == 200, confirmed.text
    api.cookies.clear()
    again = api.post(
        f"{AUTH}/login", json={"email": NEW_DOCTOR_EMAIL, "password": STAFF_PASSWORD}
    )
    assert again.json()["status"] == "MFA_CHALLENGE", again.text
