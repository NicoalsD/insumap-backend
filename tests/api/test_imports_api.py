"""Patient import endpoints over the real app with port doubles (API.md 8.4)."""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.onboarding.batch import ImportBatch, ImportTotals
from insumap.domain.onboarding.vocabulary import BatchStatus, DataOrigin, SourceFormat
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import NOW

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
BASE = "/api/v1/imports"
CSV = "text/csv"
FHIR = "application/fhir+json"
ADMIN = UUID(int=910)
DOCTOR = UUID(int=911)
ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.PATIENTS_IMPORT, PermissionCode.IMPORT_BATCHES_READ}
)
OTHER_CLINIC_BATCH = UUID(int=999)


@pytest.fixture
def api() -> IdentityApi:
    return IdentityApi()


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, frozenset()))


def upload_csv(api: IdentityApi, headers: dict[str, str], name: str) -> Any:
    return api.client.post(
        f"{BASE}/csv",
        headers={**headers, "Content-Type": CSV},
        content=(FIXTURES / name).read_bytes(),
    )


def upload_fhir(api: IdentityApi, headers: dict[str, str], name: str) -> Any:
    return api.client.post(
        f"{BASE}/fhir",
        headers={**headers, "Content-Type": FHIR},
        content=(FIXTURES / name).read_bytes(),
    )


def test_template_lists_the_required_columns(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE}/csv-template", headers=admin(api))

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0].startswith("mrn,birth_date,full_name")


def test_csv_preview_stages_and_creates_no_account(api: IdentityApi) -> None:
    headers = admin(api)

    response = upload_csv(api, headers, "pacientes_validos.csv")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == BatchStatus.PREVIEWED.value
    assert body["source"] == "CSV"
    assert body["totals"]["total"] == 3
    assert body["totals"]["valid"] == 2
    assert body["totals"]["warning"] == 1
    assert response.headers["location"] == f"{BASE}/{body['batch_id']}"
    assert api.onboarding.accounts.patients == []


def test_fhir_preview_skips_unsupported_resources_without_stopping(
    api: IdentityApi,
) -> None:
    headers = admin(api)

    response = upload_fhir(api, headers, "bundle_fhir_valido.json")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "FHIR"
    assert body["totals"]["total"] == 3
    assert body["totals"]["valid"] == 2
    assert api.onboarding.accounts.patients == []


def test_confirm_creates_the_patients_and_is_not_repeatable(api: IdentityApi) -> None:
    headers = admin(api)
    batch = upload_csv(api, headers, "pacientes_validos.csv").json()

    confirmed = api.client.post(f"{BASE}/{batch['batch_id']}/confirm", headers=headers)
    again = api.client.post(f"{BASE}/{batch['batch_id']}/confirm", headers=headers)

    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()["status"] == BatchStatus.COMPLETED.value
    assert confirmed.json()["totals"]["created"] == 3
    assert len(api.onboarding.accounts.patients) == 3
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_confirm_after_the_preview_expired_is_a_conflict(api: IdentityApi) -> None:
    headers = admin(api)
    batch = upload_csv(api, headers, "pacientes_validos.csv").json()
    api.onboarding.staged.entries.clear()

    response = api.client.post(f"{BASE}/{batch['batch_id']}/confirm", headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_batch_reads_list_get_rows_and_errors(api: IdentityApi) -> None:
    headers = admin(api)
    batch = upload_csv(api, headers, "pacientes_con_errores.csv").json()
    batch_id = batch["batch_id"]

    listed = api.client.get(BASE, headers=headers, params={"source": "CSV"})
    detail = api.client.get(f"{BASE}/{batch_id}", headers=headers)
    rejected = api.client.get(
        f"{BASE}/{batch_id}/rows", headers=headers, params={"status": "REJECTED"}
    )
    errors = api.client.get(f"{BASE}/{batch_id}/errors", headers=headers)

    assert listed.status_code == 200
    assert [item["batch_id"] for item in listed.json()["items"]] == [batch_id]
    assert detail.json()["totals"]["error"] == 3
    assert {item["row_number"] for item in rejected.json()["items"]} == {2, 3, 5}
    assert errors.headers["content-type"].startswith("text/csv")
    assert errors.text.splitlines()[0] == "row,column,cause"
    assert "birth_date,BIRTH_DATE_MISSING" in errors.text


def test_rows_are_paginated_with_a_cursor(api: IdentityApi) -> None:
    headers = admin(api)
    batch_id = upload_csv(api, headers, "pacientes_con_errores.csv").json()["batch_id"]

    first = api.client.get(
        f"{BASE}/{batch_id}/rows", headers=headers, params={"limit": 2}
    ).json()
    second = api.client.get(
        f"{BASE}/{batch_id}/rows",
        headers=headers,
        params={"limit": 2, "cursor": first["next_cursor"]},
    ).json()

    # The valid row 1 is only staged until the confirmation: rows list the stored ones.
    assert [item["row_number"] for item in first["items"]] == [2, 3]
    assert first["next_cursor"] is not None
    assert [item["row_number"] for item in second["items"]] == [4, 5]
    assert second["next_cursor"] is None


def test_another_clinics_batch_is_a_not_found_like_a_missing_one(
    api: IdentityApi,
) -> None:
    headers = admin(api)
    api.onboarding.batches.batches[OTHER_CLINIC_BATCH] = ImportBatch(
        batch_id=OTHER_CLINIC_BATCH,
        clinic_id=UUID(int=77),
        source_format=SourceFormat.CSV,
        data_origin=DataOrigin.REAL,
        status=BatchStatus.PREVIEWED,
        file_sha256="0" * 64,
        file_size_bytes=1,
        totals=ImportTotals(),
        created_by=ADMIN,
        created_at=NOW,
    )

    other = api.client.get(f"{BASE}/{OTHER_CLINIC_BATCH}", headers=headers)
    missing = api.client.get(f"{BASE}/{UUID(int=12345)}", headers=headers)

    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()


def test_a_missing_csv_column_is_a_422_naming_the_column(api: IdentityApi) -> None:
    headers = admin(api)
    response = api.client.post(
        f"{BASE}/csv",
        headers={**headers, "Content-Type": CSV},
        content=b"mrn,birth_date,full_name,document_type\nDEMO-1,1970-01-01,Nombre,CC\n",
    )

    assert response.status_code == 422
    assert response.json()["error"]["detail"]["errors"] == [
        {"field": "document_number", "type": "missing_column"}
    ]


def test_a_wrong_content_type_is_415(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/csv",
        headers={**admin(api), "Content-Type": FHIR},
        content=b"mrn\n",
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_a_csv_over_its_size_limit_is_413(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/csv",
        headers={**admin(api), "Content-Type": CSV},
        content=b"a" * (2 * 1024 * 1024 + 1),
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/csv-template"),
        ("POST", "/csv"),
        ("POST", "/fhir"),
        ("GET", ""),
        ("GET", f"/{UUID(int=1)}"),
        ("POST", f"/{UUID(int=1)}/confirm"),
    ],
)
def test_no_token_is_a_401(api: IdentityApi, method: str, path: str) -> None:
    response = api.client.request(method, f"{BASE}{path}")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_doctor_without_the_permission_is_a_403(api: IdentityApi) -> None:
    headers = doctor(api)

    assert api.client.get(f"{BASE}/csv-template", headers=headers).status_code == 403
    assert upload_csv(api, headers, "pacientes_validos.csv").status_code == 403
    assert api.client.get(BASE, headers=headers).status_code == 403


def test_an_unknown_batch_confirm_is_a_404(api: IdentityApi) -> None:
    response = api.client.post(f"{BASE}/{UUID(int=4242)}/confirm", headers=admin(api))

    assert response.status_code == 404
