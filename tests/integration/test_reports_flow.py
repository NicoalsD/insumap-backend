"""Reports over PostgreSQL 18: formats, roles, the 404 rule and the EXPORT audit."""

from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_sites_flow import _staff_headers

# ruff: noqa: F811 - pytest fixtures are reused from another module on purpose
from tests.integration.test_treatment_flow import (
    _bearer,
    _patient_token,
    goals,  # noqa: F401 - the patient_id fixture depends on it
    patient_id,  # noqa: F401 - pytest fixture, used by the tests below
)
from tests.support.db_seed import ADMIN_EMAIL, DOCTOR_EMAIL, DemoWorld

pytestmark = pytest.mark.integration

REPORTS = "/api/v1/reports"
PDF = "application/pdf"
HTML = "text/html; charset=utf-8"


def _export_rows(migrated_url: str, clinic_id: object) -> list[tuple[object, ...]]:
    with psycopg.connect(migrated_url) as conn:
        return conn.execute(
            "SELECT resource_type, action, outcome, purpose FROM audit.data_access_log"
            " WHERE clinic_id = %s AND action = 'EXPORT' ORDER BY occurred_at",
            (clinic_id,),
        ).fetchall()


def test_a_doctor_gets_the_patient_report_as_a_pdf_file(
    api: TestClient, migrated_url: str, demo_world: DemoWorld, patient_id: str
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    response = api.post(
        f"{REPORTS}/patient",
        headers=doctor,
        json={"patient_id": patient_id, "format": "pdf"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == PDF
    assert response.headers["cache-control"] == "no-store"
    assert (
        response.headers["content-disposition"] == 'attachment; filename="reporte.pdf"'
    )
    assert response.content.startswith(b"%PDF")
    rows = _export_rows(migrated_url, demo_world.clinic_id)
    assert ("REPORT", "EXPORT", "GRANTED", "CARE") in rows


def test_the_html_report_marks_the_demo_clinic_and_has_the_disclaimer(
    api: TestClient, demo_world: DemoWorld, patient_id: str
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    response = api.post(
        f"{REPORTS}/patient",
        headers=doctor,
        json={"patient_id": patient_id, "format": "html", "window": "7d"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == HTML
    body = response.text
    assert "Datos simulados" in body
    assert "no es un dispositivo médico" in body


def test_the_administrator_gets_clinic_counts_without_clinical_detail(
    api: TestClient, migrated_url: str, demo_world: DemoWorld, patient_id: str
) -> None:
    admin = _staff_headers(api, ADMIN_EMAIL)

    response = api.post(f"{REPORTS}/clinic", headers=admin, json={"format": "html"})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == HTML
    body = response.text
    assert "Indicadores de la clínica" in body
    assert "Datos simulados" in body
    assert patient_id not in body
    rows = _export_rows(migrated_url, demo_world.clinic_id)
    assert ("REPORT", "EXPORT", "GRANTED", "ADMINISTRATION") in rows


def test_the_clinic_report_as_pdf_is_a_pdf_file(
    api: TestClient, demo_world: DemoWorld
) -> None:
    admin = _staff_headers(api, ADMIN_EMAIL)

    response = api.post(f"{REPORTS}/clinic", headers=admin, json={"format": "pdf"})

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == PDF
    assert response.content.startswith(b"%PDF")


def test_the_patient_gets_an_own_report_with_consent_and_no_other_patient(
    api: TestClient, migrated_url: str, demo_world: DemoWorld, patient_id: str
) -> None:
    token = _patient_token(api)

    response = api.post(
        f"{REPORTS}/own", headers=_bearer(token), json={"format": "html"}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == HTML
    assert patient_id in response.text
    rows = _export_rows(migrated_url, demo_world.clinic_id)
    assert ("REPORT", "EXPORT", "GRANTED", "SELF") in rows


def test_no_token_is_unauthenticated_on_every_report(api: TestClient) -> None:
    for path, body in (
        ("patient", {"patient_id": str(uuid4()), "format": "pdf"}),
        ("own", {"format": "pdf"}),
        ("clinic", {"format": "pdf"}),
    ):
        response = api.post(f"{REPORTS}/{path}", json=body)
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_the_administrator_cannot_read_a_patient_report(
    api: TestClient, patient_id: str
) -> None:
    admin = _staff_headers(api, ADMIN_EMAIL)

    response = api.post(
        f"{REPORTS}/patient",
        headers=admin,
        json={"patient_id": patient_id, "format": "pdf"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_a_doctor_cannot_read_a_patient_who_is_not_assigned(
    api: TestClient, demo_world: DemoWorld
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    response = api.post(
        f"{REPORTS}/patient",
        headers=doctor,
        json={"patient_id": str(uuid4()), "format": "pdf"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_the_patient_cannot_generate_the_clinic_report(api: TestClient) -> None:
    token = _patient_token(api)

    response = api.post(
        f"{REPORTS}/clinic", headers=_bearer(token), json={"format": "pdf"}
    )

    assert response.status_code == 403


def test_unknown_fields_and_bad_formats_are_validation_errors(
    api: TestClient, patient_id: str
) -> None:
    doctor = _staff_headers(api, DOCTOR_EMAIL)

    extra = api.post(
        f"{REPORTS}/patient",
        headers=doctor,
        json={"patient_id": patient_id, "format": "pdf", "clinic_id": str(uuid4())},
    )
    bad_format = api.post(f"{REPORTS}/clinic", headers=doctor, json={"format": "docx"})

    assert extra.status_code == 422
    assert extra.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad_format.status_code == 422
