"""Messages and follow-ups over PostgreSQL 18: real grants, RLS, triggers and rows.

The seeded clinic has a clinic administrator, a doctor (MFA on the first sign in)
and a consenting patient. The doctor is assigned to the patient through the real
care team endpoint, then the thread and the controls are exercised end to end.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.support.db_seed import (
    ADMIN_EMAIL,
    DEMO_PASSWORD,
    DOCTOR_EMAIL,
    PATIENT_EMAIL,
    DemoWorld,
)

pytestmark = pytest.mark.integration

FUTURE = (datetime.now(UTC) + timedelta(days=3)).isoformat()
NOTE = "Asistió y se revisó la rutina de insulina"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _login(api: TestClient, email: str) -> Any:
    return api.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )


def _staff_headers(api: TestClient, email: str) -> dict[str, str]:
    """Enroll MFA on the first sign in, then sign in with a recovery code."""
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
    second = _login(api, email)
    verified = api.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge_token": second.json()["challenge_token"],
            "code": confirmed.json()["recovery_codes"][0],
        },
    )
    assert verified.status_code == 200, verified.text
    return _bearer(verified.json()["access_token"])


def _patient_id(migrated_url: str, user_id: UUID) -> UUID:
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT id FROM clinic.patients WHERE user_id = %s", (user_id,)
        ).fetchone()
    assert row is not None
    value = row[0]
    assert isinstance(value, UUID)
    return value


@pytest.fixture
def staff(api: TestClient, demo_world: DemoWorld) -> dict[str, dict[str, str]]:
    return {
        "admin": _staff_headers(api, ADMIN_EMAIL),
        "doctor": _staff_headers(api, DOCTOR_EMAIL),
    }


@pytest.fixture
def patient_id(migrated_url: str, demo_world: DemoWorld) -> UUID:
    return _patient_id(migrated_url, demo_world.patient_user_id)


@pytest.fixture
def assigned(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    demo_world: DemoWorld,
    patient_id: UUID,
) -> UUID:
    """The seeded doctor becomes the care team of the consenting patient."""
    response = api.post(
        "/api/v1/care-team/assignments",
        headers=staff["admin"],
        json={
            "patient_id": str(patient_id),
            "doctor_id": str(demo_world.doctor_user_id),
        },
    )
    assert response.status_code == 201, response.text
    return patient_id


def _patient_headers(api: TestClient) -> dict[str, str]:
    login = _login(api, PATIENT_EMAIL)
    assert login.status_code == 200, login.text
    return _bearer(login.json()["access_token"])


def test_patient_message_reaches_the_doctor_and_a_doctor_reply_reaches_the_patient(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    assigned: UUID,
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    patient = _patient_headers(api)

    sent = api.post(
        "/api/v1/messages",
        headers=patient,
        json={"body": "Tengo una duda sobre mi dosis"},
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["sender_role"] == "PATIENT"

    doctor_view = api.get(
        "/api/v1/messages",
        headers=staff["doctor"],
        params={"patient_id": str(assigned)},
    )
    assert doctor_view.status_code == 200, doctor_view.text
    assert doctor_view.json()["items"][0]["body"] == "Tengo una duda sobre mi dosis"

    reply = api.post(
        "/api/v1/messages",
        headers=staff["doctor"],
        json={"body": "Lo revisamos en la consulta", "patient_id": str(assigned)},
    )
    assert reply.status_code == 201, reply.text
    own = api.get("/api/v1/messages", headers=patient)
    assert [m["sender_role"] for m in own.json()["items"]] == ["DOCTOR", "PATIENT"]

    with psycopg.connect(migrated_url) as conn:
        senders = conn.execute(
            "SELECT sender_role, sender_user_id FROM messaging.messages"
            " ORDER BY sent_at"
        ).fetchall()
        notified = conn.execute(
            "SELECT notification_type FROM alerts.notifications"
            " WHERE recipient_user_id = %s",
            (demo_world.doctor_user_id,),
        ).fetchall()
    assert [row[0] for row in senders] == ["PATIENT", "DOCTOR"]
    assert ("MESSAGE",) in notified


def test_clinic_admin_cannot_read_the_thread(
    api: TestClient, staff: dict[str, dict[str, str]], assigned: UUID
) -> None:
    response = api.get(
        "/api/v1/messages", headers=staff["admin"], params={"patient_id": str(assigned)}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_doctor_follow_up_is_scheduled_closed_and_visible_to_the_patient(
    api: TestClient, staff: dict[str, dict[str, str]], assigned: UUID
) -> None:
    created = api.post(
        "/api/v1/follow-ups",
        headers=staff["doctor"],
        json={"patient_id": str(assigned), "scheduled_at": FUTURE},
    )
    assert created.status_code == 201, created.text
    follow_up_id = created.json()["id"]

    closed = api.post(
        f"/api/v1/follow-ups/{follow_up_id}/close",
        headers=staff["doctor"],
        json={"outcome": "DONE", "result_note": NOTE},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "DONE"

    listing = api.get("/api/v1/follow-ups", headers=_patient_headers(api))
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()["items"]] == [follow_up_id]
    assert listing.json()["items"][0]["status"] == "DONE"


def test_follow_up_row_keeps_the_close_time_and_note(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    assigned: UUID,
    migrated_url: str,
) -> None:
    created = api.post(
        "/api/v1/follow-ups",
        headers=staff["doctor"],
        json={"patient_id": str(assigned), "scheduled_at": FUTURE},
    )
    follow_up_id = created.json()["id"]
    api.post(
        f"/api/v1/follow-ups/{follow_up_id}/close",
        headers=staff["doctor"],
        json={"outcome": "MISSED", "result_note": NOTE},
    )

    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT kind, status, result_note, closed_at FROM care.follow_ups"
            " WHERE id = %s",
            (UUID(follow_up_id),),
        ).fetchone()
    assert row is not None
    assert row[0] == "CONTROL"
    assert row[1] == "MISSED"
    assert row[2] == NOTE
    assert row[3] is not None
