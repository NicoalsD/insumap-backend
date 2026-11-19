"""Dashboard, clinical notes, patient overview and clinic KPIs over HTTP (8.6, 8.11)."""

from uuid import UUID

import pytest

from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import (
    DASHBOARD_DOCTOR_ID,
    DASHBOARD_PATIENT_ID,
    IdentityApi,
)

BASE = "/api/v1"
TRIAGE = f"{BASE}/dashboard/triage"
UNKNOWN_PATIENT = UUID(int=0xFFFF)
DOCTOR_PERMISSIONS = frozenset(
    {
        PermissionCode.DASHBOARD_READ_ASSIGNED,
        PermissionCode.CLINICAL_NOTES_MANAGE,
        PermissionCode.PATIENTS_READ_ASSIGNED,
    }
)
ADMIN_PERMISSIONS = frozenset({PermissionCode.CLINIC_KPIS_READ})


@pytest.fixture
def api() -> IdentityApi:
    return IdentityApi()


def doctor(api: IdentityApi) -> dict[str, str]:
    token = api.staff_token(DASHBOARD_DOCTOR_ID, Role.DOCTOR, DOCTOR_PERMISSIONS)
    return api.bearer(token)


def admin(api: IdentityApi) -> dict[str, str]:
    token = api.staff_token(UUID(int=0xAD), Role.CLINIC_ADMIN, ADMIN_PERMISSIONS)
    return api.bearer(token)


def note_body(text: str = "Control estable.") -> dict[str, object]:
    return {"text": text}


# --- 401: no token --------------------------------------------------------------


def test_without_a_token_every_new_route_is_401(api: IdentityApi) -> None:
    assert api.client.get(TRIAGE).status_code == 401
    assert (
        api.client.post(
            f"{BASE}/dashboard/patients/{DASHBOARD_PATIENT_ID}/review"
        ).status_code
        == 401
    )
    notes = f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/clinical-notes"
    assert api.client.get(notes).status_code == 401
    assert api.client.post(notes, json=note_body()).status_code == 401
    assert (
        api.client.get(f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/overview").status_code
        == 401
    )
    assert api.client.get(f"{BASE}/clinic-kpis").status_code == 401


# --- 403: the role lacks the permission ----------------------------------------


def test_the_administrator_cannot_read_the_triage_list_403(api: IdentityApi) -> None:
    response = api.client.get(TRIAGE, headers=admin(api))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_the_administrator_cannot_read_clinical_notes_403(api: IdentityApi) -> None:
    response = api.client.get(
        f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/clinical-notes", headers=admin(api)
    )

    assert response.status_code == 403


def test_a_doctor_cannot_read_the_clinic_kpis_403(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE}/clinic-kpis", headers=doctor(api))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


# --- 404: not assigned or missing -------------------------------------------------


def test_an_unassigned_patient_has_no_overview_404(api: IdentityApi) -> None:
    response = api.client.get(
        f"{BASE}/patients/{UNKNOWN_PATIENT}/overview", headers=doctor(api)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_unassigned_patient_has_no_notes_404(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/patients/{UNKNOWN_PATIENT}/clinical-notes",
        json=note_body(),
        headers=doctor(api),
    )

    assert response.status_code == 404


# --- 422: validation ---------------------------------------------------------------


def test_an_unknown_field_in_a_note_is_422(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/clinical-notes",
        json={"text": "ok", "author_id": str(DASHBOARD_DOCTOR_ID)},
        headers=doctor(api),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_an_empty_note_is_422(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/clinical-notes",
        json={"text": ""},
        headers=doctor(api),
    )

    assert response.status_code == 422


def test_an_unknown_window_is_422(api: IdentityApi) -> None:
    response = api.client.get(TRIAGE, params={"window": "1y"}, headers=doctor(api))

    assert response.status_code == 422


# --- happy paths --------------------------------------------------------------------


def test_the_triage_list_orders_and_audits_the_assigned_patient(
    api: IdentityApi,
) -> None:
    response = api.client.get(TRIAGE, headers=doctor(api))

    assert response.status_code == 200
    [item] = response.json()["items"]
    assert item["patient_id"] == str(DASHBOARD_PATIENT_ID)
    assert item["is_fallback"] is True
    assert {flag["code"] for flag in item["flags"]} == {"NO_RECENT_READINGS"}
    assert item["flags"][0]["reason"]
    assert response.json()["next_cursor"] is None
    assert len(api.dashboard_audit.granted) == 1


def test_a_review_is_recorded_and_the_patient_shows_as_reviewed(
    api: IdentityApi,
) -> None:
    headers = doctor(api)

    review = api.client.post(
        f"{BASE}/dashboard/patients/{DASHBOARD_PATIENT_ID}/review", headers=headers
    )
    listed = api.client.get(TRIAGE, headers=headers).json()["items"][0]

    assert review.status_code == 200
    assert review.json()["patient_id"] == str(DASHBOARD_PATIENT_ID)
    assert listed["reviewed"] is True


def test_a_note_is_appended_and_listed_for_the_assigned_doctor(
    api: IdentityApi,
) -> None:
    headers = doctor(api)
    url = f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/clinical-notes"

    created = api.client.post(url, json=note_body("Ajustar la cena."), headers=headers)
    listed = api.client.get(url, headers=headers)

    assert created.status_code == 201
    assert created.json()["text"] == "Ajustar la cena."
    assert created.json()["corrects_note_id"] is None
    assert listed.status_code == 200
    assert [n["text"] for n in listed.json()["items"]] == ["Ajustar la cena."]


def test_a_correction_is_a_new_note_that_names_the_old_one(api: IdentityApi) -> None:
    headers = doctor(api)
    url = f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/clinical-notes"
    first = api.client.post(url, json=note_body("Error"), headers=headers).json()

    corrected = api.client.post(
        url,
        json={"text": "Corrección", "corrects_note_id": first["id"]},
        headers=headers,
    )

    assert corrected.status_code == 201
    assert corrected.json()["corrects_note_id"] == first["id"]
    assert len(api.dashboard_notes.rows) == 2


def test_the_overview_reports_the_target_and_no_plan(api: IdentityApi) -> None:
    response = api.client.get(
        f"{BASE}/patients/{DASHBOARD_PATIENT_ID}/overview", headers=doctor(api)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["patient_id"] == str(DASHBOARD_PATIENT_ID)
    assert body["target"]["range_low_mg_dl"] < body["target"]["range_high_mg_dl"]
    assert body["active_plan"] is None
    assert body["recent_readings"] == []
    # The identity clinic is a demo clinic: the marking must be consistent.
    assert body["simulated"] is True
    assert body["data_source"] == "SIMULATED"


def test_the_clinic_kpis_show_counts_and_the_activation_rate(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE}/clinic-kpis", headers=admin(api))

    assert response.status_code == 200
    body = response.json()
    assert body["total_patients"] == 4
    assert body["patients_by_status"]["ACTIVE"] == 3
    assert body["activation_rate_pct"] == 75.0
