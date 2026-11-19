"""Patient administration and own profile over PostgreSQL 18 (API.md 8.4 and 8.6).

The real schema, row level security and the audit tables: the roster query, the
status transitions with their session revocation, and the invitation revocation.
"""

from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

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

ROSTER = "/api/v1/patients"
OWN = "/api/v1/patients/own"
REASON = "Suspensión por revisión administrativa del caso"
ACTIVE_MRN = "DEMO-0001"
INVITED_MRN = "DEMO-0002"
DEMO_CLINIC_NAME = "Clínica Demo Insumap"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _enroll(api: TestClient, email: str) -> str:
    """Sign in a demo staff member, enrolling its MFA; returns its full access token."""
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


def _patient_token(api: TestClient) -> str:
    """Sign in the seeded patient (no second factor for patients)."""
    login = api.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": DEMO_PASSWORD}
    )
    assert login.status_code == 200, login.text
    assert login.json()["status"] == "AUTHENTICATED", login.text
    return str(login.json()["access_token"])


def _superuser_one(url: str, sql: str, params: tuple[object, ...] = ()) -> Any:
    """A superuser read: it bypasses row level security, to check what was written."""
    with psycopg.connect(url) as conn:
        row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0] if len(row) == 1 else row


def _patient_id(url: str, mrn: str) -> UUID:
    value = _superuser_one(url, "SELECT id FROM clinic.patients WHERE mrn = %s", (mrn,))
    assert isinstance(value, UUID)
    return value


def _outside_patient(url: str) -> UUID:
    """A patient of another clinic, inserted with the superuser."""
    with psycopg.connect(url, autocommit=True) as conn:
        clinic = conn.execute(
            "INSERT INTO clinic.clinics (name, tax_id, timezone, is_demo)"
            " VALUES ('Clínica Ajena de Prueba', '900000009-9', 'America/Bogota',"
            " false) RETURNING id"
        ).fetchone()
        assert clinic is not None
        user = conn.execute(
            "INSERT INTO iam.users (email, email_normalized, status)"
            " VALUES ('ajena.paciente@example.test', 'ajena.paciente@example.test',"
            " 'ACTIVE') RETURNING id"
        ).fetchone()
        assert user is not None
        conn.execute(
            "INSERT INTO iam.memberships (user_id, clinic_id, role_id)"
            " SELECT %s, %s, id FROM iam.roles WHERE code = 'PATIENT'",
            (user[0], clinic[0]),
        )
        patient = conn.execute(
            "INSERT INTO clinic.patients (clinic_id, user_id, mrn, full_name,"
            " birth_date, document_type, document_hash, document_hash_key_id,"
            " document_ciphertext, document_key_id, document_last4)"
            " VALUES (%s, %s, 'AJENA-0001', 'Paciente Ajeno de Prueba', '1990-01-01',"
            " 'CC', %s, %s, %s, %s, '1111') RETURNING id",
            (
                clinic[0],
                user[0],
                uuid4().hex + uuid4().hex,
                "0" * 16,
                b"invalid-document",
                "0" * 16,
            ),
        ).fetchone()
        assert patient is not None
    return UUID(str(patient[0]))


def _admin(api: TestClient) -> dict[str, str]:
    return _bearer(_enroll(api, ADMIN_EMAIL))


def _doctor(api: TestClient) -> dict[str, str]:
    return _bearer(_enroll(api, DOCTOR_EMAIL))


def _error(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


def test_roster_lists_the_clinic_with_team_and_invitation_summary(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    doctor_user = demo_world.doctor_user_id
    active = _patient_id(migrated_url, ACTIVE_MRN)
    _superuser_one(
        migrated_url,
        "INSERT INTO clinic.care_team_assignments (clinic_id, patient_id,"
        " doctor_user_id, is_primary, assigned_by) VALUES (%s, %s, %s, true, %s)"
        " RETURNING id",
        (demo_world.clinic_id, active, doctor_user, demo_world.admin_user_id),
    )

    response = api.get(ROSTER, headers=_admin(api))

    assert response.status_code == 200, response.text
    items = {item["mrn"]: item for item in response.json()["items"]}
    assert set(items) == {ACTIVE_MRN, INVITED_MRN}
    active_row = items[ACTIVE_MRN]
    assert active_row["account_status"] == "ACTIVE"
    assert active_row["primary_doctor_id"] == str(doctor_user)
    assert active_row["assigned_doctor_count"] == 1
    assert active_row["invitation_status"] is None
    assert active_row["document_last4"] == "0000"
    assert active_row["simulated"] is True
    invited_row = items[INVITED_MRN]
    assert invited_row["account_status"] == "INVITED"
    assert invited_row["primary_doctor_id"] is None
    assert invited_row["assigned_doctor_count"] == 0
    assert invited_row["invitation_status"] == "PENDING"
    assert "document_ciphertext" not in response.text
    logged = _superuser_one(
        migrated_url,
        "SELECT count(*) FROM audit.data_access_log"
        " WHERE resource_type = 'PATIENT_LIST' AND actor_user_id = %s",
        (demo_world.admin_user_id,),
    )
    assert logged == 1


def test_roster_filters_by_status_and_by_missing_doctor(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    headers = _admin(api)

    invited = api.get(
        ROSTER, headers=headers, params={"account_status": "INVITED"}
    ).json()["items"]
    unassigned = api.get(
        ROSTER, headers=headers, params={"without_doctor": "true"}
    ).json()["items"]
    batch = _superuser_one(
        migrated_url,
        "SELECT import_batch_id FROM clinic.patients WHERE mrn = %s",
        (INVITED_MRN,),
    )

    assert [item["mrn"] for item in invited] == [INVITED_MRN]
    assert {item["mrn"] for item in unassigned} == {ACTIVE_MRN, INVITED_MRN}
    assert batch is None


def test_detail_and_another_clinic_answer_the_same_not_found(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    headers = _admin(api)
    own = _patient_id(migrated_url, ACTIVE_MRN)
    other = _outside_patient(migrated_url)

    found = api.get(f"{ROSTER}/{own}", headers=headers)
    foreign = api.get(f"{ROSTER}/{other}", headers=headers)
    missing = api.get(f"{ROSTER}/{uuid4()}", headers=headers)

    assert found.status_code == 200, found.text
    assert found.json()["mrn"] == ACTIVE_MRN
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert _error(foreign) == "NOT_FOUND"


def test_suspend_ends_the_patient_session_and_reactivate_restores_it(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    admin = _admin(api)
    patient_session = _patient_token(api)
    patient = _patient_id(migrated_url, ACTIVE_MRN)

    suspended = api.post(
        f"{ROSTER}/{patient}/suspend", headers=admin, json={"reason": REASON}
    )

    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["account_status"] == "SUSPENDED"
    row = _superuser_one(
        migrated_url,
        "SELECT status, status_reason, token_version FROM iam.users WHERE id = %s",
        (demo_world.patient_user_id,),
    )
    assert row == ("SUSPENDED", REASON, 1)
    revoked = _superuser_one(
        migrated_url,
        "SELECT count(*) FROM iam.refresh_tokens WHERE user_id = %s"
        " AND revoked_reason = 'ACCOUNT_SUSPENDED'",
        (demo_world.patient_user_id,),
    )
    assert revoked >= 1
    own = api.get(OWN, headers=_bearer(patient_session))
    assert own.status_code == 401, own.text
    assert _error(own) == "SESSION_REVOKED"
    audit = _superuser_one(
        migrated_url,
        "SELECT reason FROM audit.audit_log WHERE action = 'PATIENT_SUSPENDED'"
        " AND entity_id = %s",
        (patient,),
    )
    assert audit == REASON

    reactivated = api.post(f"{ROSTER}/{patient}/reactivate", headers=admin)

    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["account_status"] == "ACTIVE"
    restored = _superuser_one(
        migrated_url,
        "SELECT status, status_reason FROM iam.users WHERE id = %s",
        (demo_world.patient_user_id,),
    )
    assert restored == ("ACTIVE", None)
    profile = api.get(OWN, headers=_bearer(_patient_token(api)))
    assert profile.status_code == 200, profile.text


def test_deactivate_revokes_the_invitation_and_is_terminal(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    admin = _admin(api)
    invited = _patient_id(migrated_url, INVITED_MRN)

    closed = api.post(
        f"{ROSTER}/{invited}/deactivate", headers=admin, json={"reason": REASON}
    )

    assert closed.status_code == 200, closed.text
    assert closed.json()["account_status"] == "DEACTIVATED"
    assert closed.json()["invitation_status"] == "REVOKED"
    status = _superuser_one(
        migrated_url,
        "SELECT status FROM iam.credential_invitations WHERE user_id ="
        " (SELECT user_id FROM clinic.patients WHERE id = %s)",
        (invited,),
    )
    assert status == "REVOKED"
    audit = _superuser_one(
        migrated_url,
        "SELECT count(*) FROM audit.audit_log WHERE action = 'PATIENT_DEACTIVATED'"
        " AND entity_id = %s",
        (invited,),
    )
    assert audit == 1
    again = api.post(f"{ROSTER}/{invited}/reactivate", headers=admin, json={})
    assert again.status_code == 409, again.text
    assert _error(again) == "INVALID_STATE_TRANSITION"


def test_doctor_cannot_read_the_roster_or_change_a_status(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    doctor = _doctor(api)
    patient = _patient_id(migrated_url, ACTIVE_MRN)

    roster = api.get(ROSTER, headers=doctor)
    change = api.post(
        f"{ROSTER}/{patient}/suspend", headers=doctor, json={"reason": REASON}
    )

    assert roster.status_code == 403, roster.text
    assert _error(roster) == "FORBIDDEN"
    assert change.status_code == 403, change.text
    status = _superuser_one(
        migrated_url,
        "SELECT status FROM iam.users WHERE id = %s",
        (demo_world.patient_user_id,),
    )
    assert status == "ACTIVE"


def test_own_profile_shows_the_clinic_and_no_clinical_data(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    response = api.get(OWN, headers=_bearer(_patient_token(api)))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(_patient_id(migrated_url, ACTIVE_MRN))
    assert body["account_status"] == "ACTIVE"
    assert body["clinic"] == {"name": DEMO_CLINIC_NAME, "simulated": True}
    assert body["target_profile"] is None
    assert body["simulated"] is True
    assert "document" not in response.text


def test_roster_rejects_an_unknown_status_filter(
    api: TestClient, demo_world: DemoWorld
) -> None:
    response = api.get(
        ROSTER, headers=_admin(api), params={"account_status": "EN_PAUSA"}
    )

    assert response.status_code == 422, response.text
    assert _error(response) == "VALIDATION_ERROR"
