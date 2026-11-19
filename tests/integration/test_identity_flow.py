"""End to end identity flows over PostgreSQL 18, the real schema and RLS."""

from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.support.db_seed import (
    ACTIVATION_CODE,
    DEMO_CLINIC_NAME,
    DEMO_PASSWORD,
    DOCTOR_EMAIL,
    INVITED_BIRTH_DATE,
    PATIENT_EMAIL,
    DemoWorld,
)

CSRF = {"X-Requested-With": "insumap-web"}
NEW_PASSWORD = "otra-contrasena-muy-larga"
pytestmark = pytest.mark.integration

NEW_EMAIL = "ana.invitada@example.test"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(api: TestClient, email: str, password: str = DEMO_PASSWORD) -> Any:
    return api.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_patient_login_me_refresh_and_logout(api: TestClient) -> None:
    login = _login(api, PATIENT_EMAIL)
    assert login.status_code == 200, login.text
    assert login.json()["status"] == "AUTHENTICATED"
    token = login.json()["access_token"]

    me = api.get("/api/v1/auth/me", headers=_bearer(token))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["role"] == "PATIENT"
    assert body["clinic"]["name"] == DEMO_CLINIC_NAME
    assert body["clinic"]["is_demo"] is True
    assert body["permissions"]
    assert body["consent_required"] is False

    refreshed = api.post("/api/v1/auth/refresh", headers=CSRF)
    assert refreshed.status_code == 200, refreshed.text
    new_token = refreshed.json()["access_token"]
    assert new_token != token

    logout = api.post("/api/v1/auth/logout", headers=CSRF | _bearer(new_token))
    assert logout.status_code == 204, logout.text
    assert api.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


def test_wrong_password_is_a_generic_401(api: TestClient) -> None:
    wrong = _login(api, PATIENT_EMAIL, "contrasena-incorrecta")
    unknown = _login(api, "nadie@example.test")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_reusing_a_rotated_refresh_revokes_the_family(api: TestClient) -> None:
    assert _login(api, PATIENT_EMAIL).status_code == 200
    stolen = api.cookies.get("__Secure-insumap_rt", path="/api/v1/auth")
    assert stolen
    assert api.post("/api/v1/auth/refresh", headers=CSRF).status_code == 200

    api.cookies.clear()
    api.cookies.set("__Secure-insumap_rt", stolen, path="/api/v1/auth")
    reuse = api.post("/api/v1/auth/refresh", headers=CSRF)

    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "SESSION_REVOKED"


def test_doctor_enrolls_mfa_then_logs_in_with_a_challenge(api: TestClient) -> None:
    first = _login(api, DOCTOR_EMAIL)
    assert first.json()["status"] == "MFA_ENROLLMENT_REQUIRED", first.text
    headers = _bearer(first.json()["access_token"])

    started = api.post("/api/v1/auth/mfa/enrollment", headers=headers)
    assert started.status_code == 200, started.text
    secret = parse_qs(urlsplit(started.json()["otpauth_uri"]).query)["secret"][0]
    totp = pyotp.TOTP(secret)

    confirmed = api.post(
        "/api/v1/auth/mfa/enrollment/confirm",
        headers=headers,
        json={"code": totp.now()},
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery = confirmed.json()["recovery_codes"]
    assert len(recovery) == 10

    second = _login(api, DOCTOR_EMAIL)
    assert second.json()["status"] == "MFA_CHALLENGE", second.text
    verified = api.post(
        "/api/v1/auth/mfa/verify",
        json={"challenge_token": second.json()["challenge_token"], "code": recovery[0]},
    )
    assert verified.status_code == 200, verified.text
    me = api.get("/api/v1/auth/me", headers=_bearer(verified.json()["access_token"]))
    assert me.json()["role"] == "DOCTOR"
    assert me.json()["mfa_enabled"] is True


def test_invited_patient_activates_with_code_and_consent(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    verified = api.post(
        "/api/v1/auth/activation/verify",
        json={
            "activation_code": ACTIVATION_CODE.lower(),
            "birth_date": INVITED_BIRTH_DATE.isoformat(),
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["clinic_name"] == DEMO_CLINIC_NAME
    assert verified.json()["email_required"] is True

    done = api.post(
        "/api/v1/auth/activation/complete",
        json={
            "activation_token": verified.json()["activation_token"],
            "new_password": NEW_PASSWORD,
            "email": NEW_EMAIL,
            "consent": {
                "privacy_notice_version_id": str(demo_world.notice_id),
                "accepted": True,
            },
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "AUTHENTICATED"

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT status FROM iam.users WHERE id = %s", (demo_world.invited_user_id,)
        ).fetchone()
    assert row == ("ACTIVE",)
    assert _login(api, NEW_EMAIL, NEW_PASSWORD).json()["status"] == "AUTHENTICATED"


def test_wrong_birth_date_is_the_single_invitation_error(api: TestClient) -> None:
    response = api.post(
        "/api/v1/auth/activation/verify",
        json={"activation_code": ACTIVATION_CODE, "birth_date": "2000-01-01"},
    )

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "INVITATION_INVALID"
