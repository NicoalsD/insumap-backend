"""Injection sites over PostgreSQL 18: the new columns, the history and the symptom."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.integration.test_notifications_flow import _bearer
from tests.support.db_seed import DEMO_PASSWORD, PATIENT_EMAIL, DemoWorld

pytestmark = pytest.mark.integration

SITES = "/api/v1/patients/own/injection-sites"


def _patient(api: TestClient) -> dict[str, str]:
    login = api.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": DEMO_PASSWORD}
    )
    return _bearer(login.json()["access_token"])


def _dose(
    hours: float, site: str | None, spot: int | None, kind: str
) -> dict[str, object]:
    when = datetime.now(UTC) - timedelta(hours=hours)
    body: dict[str, object] = {
        "kind": kind,
        "product_name": "Producto de prueba",
        "units": 8,
        "administered_at": when.isoformat(),
    }
    if site is not None:
        body["injection_site"] = site
    if spot is not None:
        body["injection_spot"] = spot
    return body


def test_a_dose_with_a_site_is_stored_listed_and_rotated(
    api: TestClient, demo_world: DemoWorld
) -> None:
    del demo_world
    headers = _patient(api)
    first = api.get(SITES, params={"kind": "BOLUS"}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["suggestion"]["site"] == "ABDOMEN_RIGHT"

    created = api.post(
        "/api/v1/insulin-doses",
        headers=headers,
        json=_dose(2, "ABDOMEN_RIGHT", 1, "BOLUS"),
    )
    assert created.status_code == 201, created.text
    assert created.json()["injection_site"] == "ABDOMEN_RIGHT"
    listed = api.get("/api/v1/insulin-doses", headers=headers).json()["items"]
    assert listed[0]["injection_spot"] == 1

    again = api.get(SITES, params={"kind": "BOLUS"}, headers=headers).json()
    assert again["suggestion"]["site"] == "ABDOMEN_LEFT"
    right = next(row for row in again["sites"] if row["site"] == "ABDOMEN_RIGHT")
    assert right["state"] == "RECENT"
    assert right["last_spot"] == 1


def test_a_dose_without_a_site_and_a_spot_without_a_site(
    api: TestClient, demo_world: DemoWorld
) -> None:
    del demo_world
    headers = _patient(api)

    plain = api.post(
        "/api/v1/insulin-doses", headers=headers, json=_dose(1, None, None, "BASAL")
    )
    bad = api.post(
        "/api/v1/insulin-doses", headers=headers, json=_dose(1, None, 2, "BASAL")
    )

    assert plain.status_code == 201, plain.text
    assert plain.json()["injection_site"] is None
    assert bad.status_code == 422


def _seed_lipohypertrophy(migrated_url: str) -> None:
    """The reset of ``demo_world`` cascades over the global catalog: seed it again."""
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO care.symptom_catalog (clinic_id, code, label_es, is_alarm)"
            " VALUES (NULL, 'LIPOHYPERTROPHY', 'Lipohipertrofia', false)"
            " ON CONFLICT (clinic_id, code) DO NOTHING"
        )


def test_lipohypertrophy_blocks_its_site_in_the_suggestion(
    api: TestClient, demo_world: DemoWorld, migrated_url: str
) -> None:
    del demo_world
    _seed_lipohypertrophy(migrated_url)
    headers = _patient(api)
    when = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    missing = api.post(
        "/api/v1/symptoms",
        headers=headers,
        json={"symptom_code": "LIPOHYPERTROPHY", "occurred_at": when},
    )
    created = api.post(
        "/api/v1/symptoms",
        headers=headers,
        json={
            "symptom_code": "LIPOHYPERTROPHY",
            "occurred_at": when,
            "injection_site": "ABDOMEN_RIGHT",
        },
    )

    assert missing.status_code == 422
    assert created.status_code == 201, created.text
    answer = api.get(SITES, params={"kind": "BOLUS"}, headers=headers).json()
    row = next(r for r in answer["sites"] if r["site"] == "ABDOMEN_RIGHT")
    assert row["state"] == "AVOID"
    assert row["reason_code"] == "LIPOHYPERTROPHY_REPORTED"
    assert answer["suggestion"]["site"] == "ABDOMEN_LEFT"
