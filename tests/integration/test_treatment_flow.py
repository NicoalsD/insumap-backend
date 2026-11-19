"""Treatment plans and templates over PostgreSQL 18: grants, RLS and triggers."""

from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_sites_flow import _login, _staff_headers
from tests.support.db_seed import (
    ADMIN_EMAIL,
    DOCTOR_EMAIL,
    PATIENT_EMAIL,
    DemoWorld,
)

pytestmark = pytest.mark.integration

BASE = "/api/v1"
PLANS = f"{BASE}/treatment-plans"
TEMPLATES = f"{BASE}/protocol-templates"
ITEM = {
    "item_type": "INSULIN",
    "name": "Basal",
    "insulin_kind": "BASAL",
    "dose_units": "10",
    "time_of_day": "08:00:00",
}


def _patient_id(migrated_url: str, demo: DemoWorld) -> str:
    with psycopg.connect(migrated_url) as conn:
        row = conn.execute(
            "SELECT id FROM clinic.patients WHERE user_id = %s", (demo.patient_user_id,)
        ).fetchone()
    assert row is not None
    return str(row[0])


PROFILE_CODE = "IT_ADULT_DEFAULT"
PROFILE_ROW = (
    "INSERT INTO care.target_profiles (clinic_id, code, label, population, version,"
    " status, is_default, range_low_mg_dl, range_high_mg_dl, very_low_mg_dl,"
    " very_high_mg_dl, tir_min_pct, tbr_l1_max_pct, tbr_l2_max_pct, tar_l1_max_pct,"
    " tar_l2_max_pct, cv_max_pct, min_data_sufficiency_pct, min_days,"
    " max_gap_minutes, hypo_episode_min_minutes, min_readings_for_cv,"
    " min_readings_for_cv_smbg, night_start, night_end, source_reference)"
    # Dummy values: the goals are data; these tests only need a default profile.
    " SELECT NULL, %s, 'Perfil de prueba', 'ADULT', 1, 'ACTIVE', true,"
    " 10, 20, 5, 30, 50, 10, 5, 40, 10, 40, 60, 7, 15, 10, 50, 20,"
    " '00:00', '06:00', 'Fuente de prueba'"
    " WHERE NOT EXISTS (SELECT 1 FROM care.target_profiles"
    " WHERE clinic_id IS NULL AND code = %s)"
)


@pytest.fixture
def goals(migrated_url: str) -> None:
    """A global default goals profile, inserted once (care rows survive a reset)."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(PROFILE_ROW, (PROFILE_CODE, PROFILE_CODE))


@pytest.fixture
def patient_id(migrated_url: str, demo_world: DemoWorld, goals: None) -> str:
    """The seeded patient, assigned to the seeded doctor (superuser, outside RLS)."""
    del goals
    patient = _patient_id(migrated_url, demo_world)
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO clinic.care_team_assignments (clinic_id, patient_id,"
            " doctor_user_id, is_primary, assigned_by, assigned_at)"
            " VALUES (%s, %s, %s, true, %s, now())",
            (
                demo_world.clinic_id,
                patient,
                demo_world.doctor_user_id,
                demo_world.admin_user_id,
            ),
        )
    return patient


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _json(response: Any) -> Any:
    assert response.status_code < 300, response.text
    return response.json()


def test_the_clinic_publishes_a_template_the_doctor_clones_into_a_plan(
    api: TestClient, demo_world: DemoWorld, patient_id: str
) -> None:
    admin = _staff_headers(api, ADMIN_EMAIL)
    doctor = _staff_headers(api, DOCTOR_EMAIL)
    template = _json(
        api.post(
            TEMPLATES,
            headers=admin,
            json={"name": f"Protocolo {uuid4().hex[:6]}", "content": {"items": [ITEM]}},
        )
    )
    created = _json(
        api.post(
            PLANS,
            headers=doctor,
            json={"patient_id": patient_id, "template_id": template["id"]},
        )
    )
    assert created["status"] == "DRAFT"
    assert created["template_id"] == template["id"]
    assert [item["name"] for item in created["items"]] == ["Basal"]

    activated = _json(api.post(f"{PLANS}/{created['id']}/activate", headers=doctor))

    assert activated["status"] == "ACTIVE"


def test_activating_a_newer_plan_supersedes_the_previous_one(
    api: TestClient, demo_world: DemoWorld, patient_id: str
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)
    first = _json(
        api.post(
            PLANS,
            headers=doctor,
            json={"patient_id": patient_id, "content": {"items": [ITEM]}},
        )
    )
    _json(api.post(f"{PLANS}/{first['id']}/activate", headers=doctor))
    version = _json(api.post(f"{PLANS}/{first['id']}/versions", headers=doctor))
    _json(
        api.patch(
            f"{PLANS}/{version['id']}",
            headers=doctor,
            json={"content": {"items": [{**ITEM, "name": "Basal nueva"}]}},
        )
    )

    _json(api.post(f"{PLANS}/{version['id']}/activate", headers=doctor))

    listed = _json(
        api.get(
            PLANS,
            headers=doctor,
            params={"patient_id": patient_id, "status": "SUPERSEDED"},
        )
    )
    assert [row["id"] for row in listed["items"]] == [first["id"]]
    own = _json(
        api.get(
            f"{BASE}/patients/own/treatment-plan", headers=_bearer(_patient_token(api))
        )
    )
    assert own["id"] == version["id"]
    assert own["version"] == 2


def test_the_database_keeps_the_photos_append_only(
    api: TestClient, migrated_url: str, demo_world: DemoWorld, patient_id: str
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)
    plan = _json(
        api.post(
            PLANS,
            headers=doctor,
            json={"patient_id": patient_id, "content": {"items": [ITEM]}},
        )
    )
    _json(
        api.patch(
            f"{PLANS}/{plan['id']}", headers=doctor, json={"content": {"items": [ITEM]}}
        )
    )

    with psycopg.connect(migrated_url) as conn, pytest.raises(psycopg.Error):
        conn.execute(
            "UPDATE care.treatment_plan_snapshots SET reason = 'cambio ilegal'"
            " WHERE plan_id = %s",
            (plan["id"],),
        )


def test_a_doctor_read_of_the_plans_is_audited_in_the_access_log(
    api: TestClient, migrated_url: str, demo_world: DemoWorld, patient_id: str
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)
    _json(api.get(PLANS, headers=doctor, params={"patient_id": patient_id}))

    with psycopg.connect(migrated_url) as conn:
        count = conn.execute(
            "SELECT count(*) FROM audit.data_access_log"
            " WHERE resource_type = 'TREATMENT_PLAN' AND patient_id = %s",
            (patient_id,),
        ).fetchone()
    assert count is not None
    assert count[0] >= 1


def test_the_administrator_cannot_read_a_clinical_plan(
    api: TestClient, demo_world: DemoWorld, patient_id: str
) -> None:
    admin = _staff_headers(api, ADMIN_EMAIL)

    response = api.get(PLANS, headers=admin, params={"patient_id": patient_id})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def _patient_token(api: TestClient) -> str:
    login = _login(api, PATIENT_EMAIL)
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"])
