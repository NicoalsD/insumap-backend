"""Patient credentials over PostgreSQL 18: issued codes activate through the real flow.

The proof that matters: a code issued here is accepted by the existing
``POST /auth/activation/verify`` (and then completes the activation), a re-issued
or revoked code is refused with ``410 INVITATION_INVALID``, and the code never
appears in the database, the audit trail or a log.
"""

import re
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient

from tests.support.db_seed import (
    ADMIN_EMAIL,
    DEMO_CLINIC_NAME,
    DEMO_PASSWORD,
    DOCTOR_EMAIL,
    DemoWorld,
    add_imported_patient,
)
from tests.support.notifications import InMemoryChannel

pytestmark = pytest.mark.integration

ISSUE = "/api/v1/patients/{patient_id}/credential-invitations"
BATCH = "/api/v1/credential-invitations/batch"
REVOKE = "/api/v1/credential-invitations/{invitation_id}/revoke"
VERIFY = "/api/v1/auth/activation/verify"
COMPLETE = "/api/v1/auth/activation/complete"
CSRF = {"X-Requested-With": "insumap-web"}
IMPORTED_BIRTH_DATE = date(1990, 1, 20)
CONTACT_EMAIL = "lucia.importada@example.test"
NEW_PASSWORD = "frase larga para activar la cuenta 2026"
CODE_IN_LINK = re.compile(r"#code=([0-9A-Z-]+)")
CODE_PATTERN = re.compile(r"^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _enroll(api: TestClient, email: str) -> str:
    """Sign in a demo staff member, enrolling its MFA; returns its access token."""
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
    return str(confirmed.json()["access_token"])


@pytest.fixture
def imported(migrated_url: str, demo_world: DemoWorld) -> tuple[UUID, UUID]:
    """An imported patient of the demo clinic: ``(user_id, patient_id)``."""
    with psycopg.connect(migrated_url) as conn:
        return add_imported_patient(
            conn,
            demo_world.clinic_id,
            "DEMO-0100",
            "Lucía Importada Demo",
            IMPORTED_BIRTH_DATE,
            CONTACT_EMAIL,
        )


def _issue(
    api: TestClient, token: str, patient_id: UUID, channel: str = "PRINT"
) -> Any:
    return api.post(
        ISSUE.format(patient_id=patient_id),
        headers=_bearer(token),
        json={"channel": channel},
    )


def _verify(api: TestClient, code: str) -> Any:
    return api.post(
        VERIFY,
        json={
            "activation_code": code,
            "birth_date": IMPORTED_BIRTH_DATE.isoformat(),
        },
    )


def _one(url: str, sql: str, params: tuple[object, ...]) -> tuple[Any, ...]:
    """A superuser read: it bypasses row level security, to check what was written."""
    with psycopg.connect(url) as conn:
        row = conn.execute(sql, params).fetchone()
    assert row is not None
    return tuple(row)


def test_a_printed_code_activates_through_the_existing_verify_endpoint(
    api: TestClient,
    imported: tuple[UUID, UUID],
    migrated_url: str,
    demo_world: DemoWorld,
) -> None:
    user_id, patient_id = imported
    admin = _enroll(api, ADMIN_EMAIL)

    issued = _issue(api, admin, patient_id)
    assert issued.status_code == 201, issued.text
    code = issued.json()["activation_code"]
    assert CODE_PATTERN.match(code)
    assert _one(
        migrated_url, "SELECT status FROM iam.users WHERE id = %s", (user_id,)
    ) == ("INVITED",)

    verified = _verify(api, code.lower().replace("-", ""))

    assert verified.status_code == 200, verified.text
    assert verified.json()["clinic_name"] == DEMO_CLINIC_NAME
    assert verified.json()["email_required"] is False
    assert str(verified.json()["privacy_notice_version_id"]) == str(
        demo_world.notice_id
    )

    done = api.post(
        COMPLETE,
        json={
            "activation_token": verified.json()["activation_token"],
            "new_password": NEW_PASSWORD,
            "email": None,
            "consent": {
                "privacy_notice_version_id": str(demo_world.notice_id),
                "accepted": True,
            },
        },
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "AUTHENTICATED"
    assert _one(
        migrated_url, "SELECT status FROM iam.users WHERE id = %s", (user_id,)
    ) == ("ACTIVE",)


def test_reissuing_refuses_the_old_code_and_accepts_the_new_one(
    api: TestClient, imported: tuple[UUID, UUID], migrated_url: str
) -> None:
    _, patient_id = imported
    admin = _enroll(api, ADMIN_EMAIL)
    first = _issue(api, admin, patient_id).json()["activation_code"]
    second_issue = _issue(api, admin, patient_id)
    assert second_issue.status_code == 201, second_issue.text
    second = second_issue.json()["activation_code"]

    old = _verify(api, first)
    new = _verify(api, second)

    assert old.status_code == 410
    assert old.json()["error"]["code"] == "INVITATION_INVALID"
    assert new.status_code == 200, new.text
    replaced = _one(
        migrated_url,
        "SELECT status, replaced_by_id IS NOT NULL FROM iam.credential_invitations"
        " WHERE patient_id = %s AND status = 'REVOKED'",
        (patient_id,),
    )
    assert replaced == ("REVOKED", True)


def test_revoking_returns_the_account_to_imported_and_the_code_stops_working(
    api: TestClient, imported: tuple[UUID, UUID], migrated_url: str
) -> None:
    user_id, patient_id = imported
    admin = _enroll(api, ADMIN_EMAIL)
    issued = _issue(api, admin, patient_id).json()
    code = issued["activation_code"]

    revoked = api.post(
        REVOKE.format(invitation_id=issued["invitation_id"]), headers=_bearer(admin)
    )

    assert revoked.status_code == 204, revoked.text
    assert _one(
        migrated_url, "SELECT status FROM iam.users WHERE id = %s", (user_id,)
    ) == ("IMPORTED",)
    assert _one(
        migrated_url,
        "SELECT status, revoked_by IS NOT NULL FROM iam.credential_invitations"
        " WHERE id = %s",
        (UUID(issued["invitation_id"]),),
    ) == ("REVOKED", True)
    refused = _verify(api, code)
    assert refused.status_code == 410
    assert refused.json()["error"]["code"] == "INVITATION_INVALID"


def test_email_delivers_a_link_whose_code_activates(
    api: TestClient, imported: tuple[UUID, UUID], mail: InMemoryChannel
) -> None:
    _, patient_id = imported
    admin = _enroll(api, ADMIN_EMAIL)

    issued = _issue(api, admin, patient_id, channel="EMAIL")

    assert issued.status_code == 201, issued.text
    assert issued.json()["activation_code"] is None
    (sent,) = mail.delivered
    assert sent.recipient.address == CONTACT_EMAIL
    match = CODE_IN_LINK.search(sent.body)
    assert match is not None, sent.body
    assert _verify(api, match.group(1)).status_code == 200


def test_the_code_is_not_stored_in_clear_nor_in_the_audit_trail(
    api: TestClient, imported: tuple[UUID, UUID], migrated_url: str
) -> None:
    _, patient_id = imported
    admin = _enroll(api, ADMIN_EMAIL)
    issued = _issue(api, admin, patient_id).json()
    code = issued["activation_code"]

    (stored_hash,) = _one(
        migrated_url,
        "SELECT code_hash FROM iam.credential_invitations WHERE id = %s",
        (UUID(issued["invitation_id"]),),
    )
    assert code.replace("-", "") not in stored_hash
    assert len(stored_hash) == 64
    audit = _one(
        migrated_url,
        "SELECT count(*), max(entity_id::text), max(action) FROM audit.audit_log"
        " WHERE action = 'CREDENTIALS_ISSUED'"
        " AND entity_type = 'CREDENTIAL_INVITATION'",
        (),
    )
    assert audit == (1, issued["invitation_id"], "CREDENTIALS_ISSUED")
    with psycopg.connect(migrated_url) as conn:
        dump = conn.execute(
            "SELECT row_to_json(a)::text FROM audit.audit_log AS a"
        ).fetchall()
    assert all(code.replace("-", "") not in row[0] for row in dump)


def test_a_batch_reports_each_patient_against_the_real_database(
    api: TestClient,
    imported: tuple[UUID, UUID],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    _, imported_patient = imported
    (active_patient,) = _one(
        migrated_url,
        "SELECT id FROM clinic.patients WHERE user_id = %s",
        (demo_world.patient_user_id,),
    )
    missing = uuid4()
    admin = _enroll(api, ADMIN_EMAIL)

    response = api.post(
        BATCH,
        headers=_bearer(admin),
        json={
            "patient_ids": [str(imported_patient), str(active_patient), str(missing)],
            "channel": "PRINT",
        },
    )

    assert response.status_code == 200, response.text
    first, second, third = response.json()["items"]
    assert first["status"] == "ISSUED"
    assert CODE_PATTERN.match(first["activation_code"])
    assert second["error_code"] == "INVALID_STATE_TRANSITION"
    assert third["error_code"] == "NOT_FOUND"
    assert second["activation_code"] is None


def test_a_doctor_cannot_issue_a_code(
    api: TestClient, imported: tuple[UUID, UUID]
) -> None:
    _, patient_id = imported
    doctor = _enroll(api, DOCTOR_EMAIL)

    response = _issue(api, doctor, patient_id)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_active_patient_is_not_reissued_with_a_print_code(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    (active_patient,) = _one(
        migrated_url,
        "SELECT id FROM clinic.patients WHERE user_id = %s",
        (demo_world.patient_user_id,),
    )
    admin = _enroll(api, ADMIN_EMAIL)

    response = _issue(api, admin, active_patient)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
