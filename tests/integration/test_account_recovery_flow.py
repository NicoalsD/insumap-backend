"""Password reset and email verification over PostgreSQL and RLS."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.support.db_seed import (
    ACTIVATION_CODE,
    DEMO_PASSWORD,
    INVITED_BIRTH_DATE,
    PATIENT_EMAIL,
    DemoWorld,
)
from tests.support.notifications import InMemoryChannel

pytestmark = pytest.mark.integration

NEW_PASSWORD = "otra-contrasena-muy-larga"
NEW_EMAIL = "ana.invitada@example.test"


def _login(api: TestClient, email: str, password: str) -> int:
    response = api.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    return int(response.status_code)


def _verify_email_of(conn_url: str, email: str) -> None:
    with psycopg.connect(conn_url) as conn:
        conn.execute(
            "UPDATE iam.users SET email_verified_at = now()"
            " WHERE email_normalized = %s",
            (email,),
        )


def test_reset_needs_a_verified_email_then_replaces_the_password(
    api: TestClient, migrated_url: str, mail: InMemoryChannel
) -> None:
    assert (
        api.post(
            "/api/v1/auth/password-reset/request", json={"email": PATIENT_EMAIL}
        ).status_code
        == 202
    )
    assert mail.delivered == []

    _verify_email_of(migrated_url, PATIENT_EMAIL)
    api.post("/api/v1/auth/password-reset/request", json={"email": PATIENT_EMAIL})
    [message] = mail.delivered
    token = message.token()

    done = api.post(
        "/api/v1/auth/password-reset/complete",
        json={"token": token, "new_password": NEW_PASSWORD},
    )
    again = api.post(
        "/api/v1/auth/password-reset/complete",
        json={"token": token, "new_password": NEW_PASSWORD},
    )

    assert done.status_code == 204, done.text
    assert again.status_code == 410
    assert _login(api, PATIENT_EMAIL, NEW_PASSWORD) == 200
    assert _login(api, PATIENT_EMAIL, DEMO_PASSWORD) == 401
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT token_version FROM iam.users WHERE email_normalized = %s",
            (PATIENT_EMAIL,),
        ).fetchone()
        events = conn.execute(
            "SELECT event_type FROM iam.security_events ORDER BY occurred_at"
        ).fetchall()
    assert row is not None
    assert row[0] >= 1
    assert ("PASSWORD_RESET_REQUESTED",) in events
    assert ("PASSWORD_CHANGED",) in events


def test_activation_emails_the_verification_link_and_confirming_it_persists(
    api: TestClient, demo_world: DemoWorld, migrated_url: str, mail: InMemoryChannel
) -> None:
    verified = api.post(
        "/api/v1/auth/activation/verify",
        json={
            "activation_code": ACTIVATION_CODE,
            "birth_date": INVITED_BIRTH_DATE.isoformat(),
        },
    )
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
    [message] = mail.delivered

    confirmed = api.post(
        "/api/v1/auth/email-verification/confirm", json={"token": message.token()}
    )

    assert confirmed.status_code == 204, confirmed.text
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT email_verified_at IS NOT NULL FROM iam.users"
            " WHERE email_normalized = %s",
            (NEW_EMAIL,),
        ).fetchone()
    assert row == (True,)
    api.post("/api/v1/auth/password-reset/request", json={"email": NEW_EMAIL})
    assert len(mail.delivered) == 2


def test_an_unknown_token_is_the_single_410(api: TestClient) -> None:
    for path, body in (
        ("/api/v1/auth/email-verification/confirm", {"token": "nope"}),
        (
            "/api/v1/auth/password-reset/complete",
            {"token": "nope", "new_password": NEW_PASSWORD},
        ),
    ):
        response = api.post(path, json=body)

        assert response.status_code == 410
        assert response.json()["error"]["code"] == "INVITATION_INVALID"
