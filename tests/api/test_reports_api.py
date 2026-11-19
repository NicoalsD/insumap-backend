"""Report endpoints over the real app with port doubles (API.md 8.11)."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.domain.clinic.clinic import Clinic, ClinicStatus
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import (
    CLINIC,
    NOTICE_ID,
    NOW,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)
from tests.support.metrics_factories import series

PATIENT_EMAIL = "paciente@example.test"
DOCTOR = UUID(int=930)
DEMO_CLINIC = Clinic(
    clinic_id=CLINIC.clinic_id,
    name="Clínica demo",
    tax_id="900000001",
    timezone="America/Bogota",
    status=ClinicStatus.ACTIVE,
    is_demo=True,
    created_at=NOW,
)
ADMIN = UUID(int=931)
UNKNOWN_PATIENT = UUID(int=9999)
DAYS_OF_DATA = 15
READINGS_PER_DAY = 24 * 12
PDF = "application/pdf"
HTML = "text/html; charset=utf-8"
REPORTS = "/api/v1/reports"
DOCTOR_PERMISSIONS = frozenset(
    {
        PermissionCode.REPORTS_GENERATE_ASSIGNED,
        PermissionCode.METRICS_READ_ASSIGNED,
        PermissionCode.PATIENTS_READ_ASSIGNED,
        PermissionCode.TREATMENT_PLANS_MANAGE,
    }
)
ADMIN_PERMISSIONS = frozenset(
    {
        PermissionCode.REPORTS_GENERATE_CLINIC,
        PermissionCode.PATIENTS_READ_ROSTER,
        PermissionCode.ALERTS_READ_SUMMARY,
    }
)
PATIENT_PERMISSIONS = frozenset(
    {
        PermissionCode.REPORTS_GENERATE_OWN,
        PermissionCode.METRICS_READ_OWN,
        PermissionCode.RECORDS_READ_OWN,
        PermissionCode.TREATMENT_PLANS_READ_OWN,
    }
)


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PATIENT_PERMISSIONS
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=932),
                clinic_id=CLINIC.clinic_id,
                patient_id=PATIENT_ID,
                privacy_notice_version_id=NOTICE_ID,
                scope=ConsentScope.SENSITIVE_DATA_PROCESSING,
                action=ConsentAction.ACCEPTED,
                occurred_at=NOW,
                recorded_by=PATIENT_USER,
            )
        ]
    )
    api.clinics.rows[CLINIC.clinic_id] = DEMO_CLINIC
    api.records.patients.assigned.add((DOCTOR, PATIENT_ID))
    api.records.series.points_by_patient[PATIENT_ID] = series(
        NOW - timedelta(days=DAYS_OF_DATA), [100] * (DAYS_OF_DATA * READINGS_PER_DAY)
    )
    return api


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def test_a_doctor_gets_the_patient_report_as_pdf(api: IdentityApi) -> None:
    response = api.client.post(
        f"{REPORTS}/patient",
        headers=doctor(api),
        json={"patient_id": str(PATIENT_ID), "format": "pdf"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == PDF
    assert response.content.startswith(b"%PDF")


def test_a_doctor_gets_the_same_patient_report_as_html(api: IdentityApi) -> None:
    response = api.client.post(
        f"{REPORTS}/patient",
        headers=doctor(api),
        json={"patient_id": str(PATIENT_ID), "format": "html", "window": "7d"},
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == HTML
    assert "Reporte del paciente" in response.text
    assert "no es un dispositivo médico" in response.text


def test_the_patient_gets_an_own_report(api: IdentityApi) -> None:
    response = api.client.post(
        f"{REPORTS}/own", headers=patient(api), json={"format": "pdf"}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == PDF


def test_the_administrator_gets_the_clinic_report(api: IdentityApi) -> None:
    response = api.client.post(
        f"{REPORTS}/clinic", headers=admin(api), json={"format": "html"}
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == HTML
    assert "Indicadores de la clínica" in response.text


def test_no_token_is_unauthenticated(api: IdentityApi) -> None:
    response = api.client.post(
        f"{REPORTS}/patient",
        json={"patient_id": str(PATIENT_ID), "format": "pdf"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_staff_member_without_the_permission_is_forbidden(
    api: IdentityApi,
) -> None:
    without = api.bearer(
        api.staff_token(
            DOCTOR, Role.DOCTOR, frozenset({PermissionCode.METRICS_READ_ASSIGNED})
        )
    )

    response = api.client.post(
        f"{REPORTS}/patient",
        headers=without,
        json={"patient_id": str(PATIENT_ID), "format": "pdf"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_unassigned_or_missing_patient_answers_not_found(api: IdentityApi) -> None:
    response = api.client.post(
        f"{REPORTS}/patient",
        headers=doctor(api),
        json={"patient_id": str(UNKNOWN_PATIENT), "format": "pdf"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_unknown_field_or_a_bad_format_is_a_validation_error(
    api: IdentityApi,
) -> None:
    unknown = api.client.post(
        f"{REPORTS}/patient",
        headers=doctor(api),
        json={"patient_id": str(PATIENT_ID), "format": "pdf", "extra": True},
    )
    bad = api.client.post(
        f"{REPORTS}/clinic", headers=admin(api), json={"format": "docx"}
    )

    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad.status_code == 422
