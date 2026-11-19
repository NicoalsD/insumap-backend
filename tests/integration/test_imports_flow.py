"""Patient import over PostgreSQL 18: RLS, the real tables and the confirmation.

The migrations of ``insumap-database`` are applied to ``it_importacion``; the
API connects as ``insumap_app``, so RLS applies to every statement.
"""

from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_users_flow import _admin_token, _bearer
from tests.support.db_seed import ADMIN_EMAIL, DemoWorld

pytestmark = pytest.mark.integration

BASE = "/api/v1/imports"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CSV = "text/csv"


def _upload(api: TestClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    response = api.post(
        f"{BASE}/csv",
        headers={**headers, "Content-Type": CSV},
        content=(FIXTURES / name).read_bytes(),
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_preview_then_confirm_creates_imported_patients_with_sealed_documents(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    headers = _bearer(_admin_token(api))
    batch = _upload(api, headers, "pacientes_validos.csv")

    confirmed = api.post(f"{BASE}/{batch['batch_id']}/confirm", headers=headers)

    assert confirmed.status_code == 202, confirmed.text
    assert confirmed.json()["totals"]["created"] == 3
    with psycopg.connect(migrated_url) as conn:
        rows = conn.execute(
            "SELECT p.mrn, u.status, p.document_last4, length(p.document_ciphertext),"
            " p.document_hash_key_id, p.user_id = u.id"
            " FROM clinic.patients p JOIN iam.users u ON u.id = p.user_id"
            " WHERE p.import_batch_id = %s ORDER BY p.mrn",
            (batch["batch_id"],),
        ).fetchall()
    assert [row[0] for row in rows] == ["DEMO-000001", "DEMO-000002", "DEMO-000003"]
    assert {row[1] for row in rows} == {"IMPORTED"}
    assert rows[0][2] == "0304"
    assert all(row[3] > 0 for row in rows)
    assert all(row[5] for row in rows)


def test_imported_accounts_have_no_password_and_no_email(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    headers = _bearer(_admin_token(api))
    batch = _upload(api, headers, "pacientes_validos.csv")
    api.post(f"{BASE}/{batch['batch_id']}/confirm", headers=headers)

    with psycopg.connect(migrated_url) as conn:
        found = conn.execute(
            "SELECT count(*) FROM iam.users u"
            " JOIN clinic.patients p ON p.user_id = u.id"
            " WHERE p.import_batch_id = %s AND u.password_hash IS NULL"
            " AND u.email IS NULL",
            (batch["batch_id"],),
        ).fetchone()
    assert found is not None
    assert found[0] == 3


def test_a_second_import_of_the_same_patients_skips_them(
    api: TestClient, demo_world: DemoWorld
) -> None:
    headers = _bearer(_admin_token(api))
    first = _upload(api, headers, "pacientes_validos.csv")
    api.post(f"{BASE}/{first['batch_id']}/confirm", headers=headers)

    second = _upload(api, headers, "pacientes_validos.csv")

    assert second["totals"]["valid"] == 0
    assert second["totals"]["skipped"] == 3


def test_another_clinics_batch_is_not_visible(
    api: TestClient, demo_world: DemoWorld
) -> None:
    headers = _bearer(_admin_token(api))
    missing = api.get(f"{BASE}/00000000-0000-7000-8000-000000000999", headers=headers)

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_error_report_contains_no_personal_data(
    api: TestClient, demo_world: DemoWorld
) -> None:
    headers = _bearer(_admin_token(api))
    batch = _upload(api, headers, "pacientes_con_errores.csv")

    report = api.get(f"{BASE}/{batch['batch_id']}/errors", headers=headers)

    assert report.status_code == 200
    assert "Sin Fecha" not in report.text
    assert "SIM-6070809" not in report.text
    assert ADMIN_EMAIL not in report.text
