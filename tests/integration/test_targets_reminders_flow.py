"""Goals and reminders over PostgreSQL 18: real grants, RLS, triggers and indexes.

The seeded clinic has a clinic administrator, a doctor (who gets MFA on the first
sign in), a consenting patient and an invited patient. The doctor is assigned to
the consenting patient through the real care team endpoint.
"""

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

PROFILES = "/api/v1/target-profiles"
REASON = "Ajuste aprobado por el comité de la clínica"


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


def _profile_body(code: str = "CLINIC_TARGETS") -> dict[str, Any]:
    """Fixture values, not clinical rules: they only have to be coherent."""
    return {
        "code": code,
        "label": "Metas de la clínica",
        "population": "ADULT",
        "is_default": False,
        "range_low_mg_dl": 70,
        "range_high_mg_dl": 180,
        "very_low_mg_dl": 54,
        "very_high_mg_dl": 250,
        "tir_min_pct": 70,
        "tbr_l1_max_pct": 4,
        "tbr_l2_max_pct": 1,
        "tar_l1_max_pct": 25,
        "tar_l2_max_pct": 5,
        "cv_max_pct": 36,
        "min_data_sufficiency_pct": 70,
        "min_days": 14,
        "max_gap_minutes": 15,
        "hypo_episode_min_minutes": 15,
        "min_readings_for_cv": 100,
        "min_readings_for_cv_smbg": 3,
        "night_start": "00:00",
        "night_end": "06:00",
        "source_reference": "Consenso de prueba, tabla 1",
    }


@pytest.fixture
def staff(api: TestClient, demo_world: DemoWorld) -> dict[str, dict[str, str]]:
    admin = _staff_headers(api, ADMIN_EMAIL)
    doctor = _staff_headers(api, DOCTOR_EMAIL)
    return {"admin": admin, "doctor": doctor}


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


def test_admin_creates_a_profile_and_the_doctor_reads_it_not_writes(
    api: TestClient, staff: dict[str, dict[str, str]]
) -> None:
    created = api.post(PROFILES, headers=staff["admin"], json=_profile_body())

    assert created.status_code == 201, created.text
    assert created.json()["version"] == 1
    assert created.json()["status"] == "ACTIVE"

    doctor_list = api.get(PROFILES, headers=staff["doctor"])
    doctor_write = api.post(
        PROFILES, headers=staff["doctor"], json=_profile_body("OTHER_CODE")
    )

    assert doctor_list.status_code == 200, doctor_list.text
    assert created.json()["id"] in [i["id"] for i in doctor_list.json()["items"]]
    assert doctor_write.status_code == 403


def test_a_second_version_retires_the_first_in_the_database(
    api: TestClient, staff: dict[str, dict[str, str]], migrated_url: str
) -> None:
    profile = api.post(PROFILES, headers=staff["admin"], json=_profile_body()).json()

    version = api.post(
        f"{PROFILES}/{profile['id']}/versions",
        headers=staff["admin"],
        json={"tir_min_pct": 75, "change_reason": REASON},
    )
    detail = api.get(f"{PROFILES}/{profile['id']}", headers=staff["admin"])

    assert version.status_code == 201, version.text
    assert version.json()["version"] == 2
    history = [(v["version"], v["status"]) for v in detail.json()["versions"]]
    assert history == [(1, "RETIRED"), (2, "ACTIVE")]
    with psycopg.connect(migrated_url) as conn:
        active = conn.execute(
            "SELECT count(*) FROM care.target_profiles"
            " WHERE code = 'CLINIC_TARGETS' AND status = 'ACTIVE'"
        ).fetchone()
    assert active is not None and active[0] == 1


def test_active_version_cannot_be_edited_in_place(
    migrated_url: str, api: TestClient, staff: dict[str, dict[str, str]]
) -> None:
    profile = api.post(PROFILES, headers=staff["admin"], json=_profile_body()).json()

    with psycopg.connect(migrated_url) as conn, pytest.raises(psycopg.Error):
        conn.execute(
            "UPDATE care.target_profiles SET tir_min_pct = 10 WHERE id = %s",
            (profile["id"],),
        )


def test_doctor_assigns_the_profile_to_his_patient(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    assigned: UUID,
) -> None:
    profile = api.post(PROFILES, headers=staff["admin"], json=_profile_body()).json()

    response = api.put(
        f"/api/v1/patients/{assigned}/target-profile",
        headers=staff["doctor"],
        json={"target_profile_id": profile["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["target_profile_id"] == profile["id"]


def test_admin_cannot_assign_a_profile_and_an_unassigned_patient_is_not_found(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    profile = api.post(PROFILES, headers=staff["admin"], json=_profile_body()).json()
    invited = _patient_id(migrated_url, demo_world.invited_user_id)

    as_admin = api.put(
        f"/api/v1/patients/{invited}/target-profile",
        headers=staff["admin"],
        json={"target_profile_id": profile["id"]},
    )
    unassigned = api.put(
        f"/api/v1/patients/{invited}/target-profile",
        headers=staff["doctor"],
        json={"target_profile_id": profile["id"]},
    )

    assert as_admin.status_code == 403
    assert unassigned.status_code == 404
    assert unassigned.json()["error"]["code"] == "NOT_FOUND"


def test_doctor_schedules_and_patient_adjusts_a_reminder(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    assigned: UUID,
) -> None:
    created = api.post(
        f"/api/v1/patients/{assigned}/reminders",
        headers=staff["doctor"],
        json={
            "reminder_type": "MEASUREMENT",
            "schedule": {"local_time": "07:30", "days_of_week": [1, 3, 5]},
        },
    )
    assert created.status_code == 201, created.text
    reminder_id = created.json()["id"]

    patient = _login(api, PATIENT_EMAIL)
    headers = _bearer(patient.json()["access_token"])
    listed = api.get("/api/v1/reminders", headers=headers)
    adjusted = api.patch(
        f"/api/v1/reminders/{reminder_id}",
        headers=headers,
        json={"schedule": {"local_time": "09:00"}},
    )

    assert listed.status_code == 200, listed.text
    assert reminder_id in [i["id"] for i in listed.json()["items"]]
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["schedule"]["local_time"] == "09:00:00"
    assert adjusted.json()["schedule"]["days_of_week"] is None


def test_doctor_cannot_schedule_for_an_unassigned_patient(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    demo_world: DemoWorld,
    migrated_url: str,
) -> None:
    invited = _patient_id(migrated_url, demo_world.invited_user_id)
    reminder = api.post(
        f"/api/v1/patients/{invited}/reminders",
        headers=staff["doctor"],
        json={"reminder_type": "CONTROL", "schedule": {"local_time": "08:00"}},
    )
    assert reminder.status_code == 404
    assert reminder.json()["error"]["code"] == "NOT_FOUND"

    patient = _login(api, PATIENT_EMAIL)
    listed = api.get(
        "/api/v1/reminders", headers=_bearer(patient.json()["access_token"])
    )

    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []


def _foreign_profile(migrated_url: str) -> UUID:
    """A profile of another clinic, inserted as superuser (RLS does not apply)."""
    with psycopg.connect(migrated_url) as conn:
        clinic = conn.execute(
            "INSERT INTO clinic.clinics (name, tax_id, timezone, is_demo)"
            " VALUES ('Clínica ajena', '900000001-1', 'America/Bogota', false)"
            " RETURNING id"
        ).fetchone()
        assert clinic is not None
        row = conn.execute(
            "INSERT INTO care.target_profiles (clinic_id, code, label, population,"
            " version, status, is_default, range_low_mg_dl, range_high_mg_dl,"
            " very_low_mg_dl, very_high_mg_dl, tir_min_pct, tbr_l1_max_pct,"
            " tbr_l2_max_pct, tar_l1_max_pct, tar_l2_max_pct, cv_max_pct,"
            " min_data_sufficiency_pct, min_days, max_gap_minutes,"
            " hypo_episode_min_minutes, min_readings_for_cv,"
            " min_readings_for_cv_smbg, night_start, night_end, source_reference)"
            " VALUES (%s, 'FOREIGN_TARGETS', 'Metas ajenas', 'ADULT', 1, 'ACTIVE',"
            " false, 70, 180, 54, 250, 70, 4, 1, 25, 5, 36, 70, 14, 15, 15, 100, 3,"
            " '00:00', '06:00', 'Fuente ajena')"
            " RETURNING id",
            (clinic[0],),
        ).fetchone()
    assert row is not None
    value = row[0]
    assert isinstance(value, UUID)
    return value


def test_another_clinics_profile_is_invisible_to_this_clinic(
    api: TestClient,
    staff: dict[str, dict[str, str]],
    assigned: UUID,
    migrated_url: str,
) -> None:
    foreign = _foreign_profile(migrated_url)

    detail = api.get(f"{PROFILES}/{foreign}", headers=staff["admin"])
    listed = api.get(PROFILES, headers=staff["admin"])
    assigned_response = api.put(
        f"/api/v1/patients/{assigned}/target-profile",
        headers=staff["doctor"],
        json={"target_profile_id": str(foreign)},
    )

    assert detail.status_code == 404
    assert detail.json()["error"]["code"] == "NOT_FOUND"
    assert str(foreign) not in [i["id"] for i in listed.json()["items"]]
    assert assigned_response.status_code == 404
    assert assigned_response.json()["error"]["code"] == "NOT_FOUND"
