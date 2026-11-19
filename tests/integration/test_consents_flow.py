"""Consent and privacy flow over PostgreSQL with row level security (API.md 8.13)."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_notifications_flow import _bearer, _staff_headers
from tests.support.db_seed import ADMIN_EMAIL, DEMO_PASSWORD, PATIENT_EMAIL, DemoWorld

OWN = "/api/v1/consents/own"
WITHDRAW = f"{OWN}/withdrawals"
REQUESTS = "/api/v1/privacy-requests"
NOTE = "Solicitud revisada por la clínica"


def _patient_headers(api: TestClient) -> dict[str, str]:
    login = api.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": DEMO_PASSWORD}
    )
    return _bearer(login.json()["access_token"])


def test_the_seeded_patient_has_the_consent_in_force(
    api: TestClient, demo_world: DemoWorld
) -> None:
    body = api.get(OWN, headers=_patient_headers(api)).json()

    assert body["consent_required"] is False
    assert body["accepted_version_id"] == str(demo_world.notice_id)
    assert body["current_version_id"] == str(demo_world.notice_id)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RLS on clinic.privacy_notice_versions needs a clinic context, which the "
        "pre-login read does not have: a SECURITY DEFINER lookup is requested"
    ),
)
def test_the_public_notice_is_readable_before_login(
    api: TestClient, demo_world: DemoWorld
) -> None:
    response = api.get(f"/api/v1/public/privacy-notices/{demo_world.notice_id}")

    assert response.status_code == 200


def test_withdrawing_blocks_new_requests_until_accepted_again(
    api: TestClient, demo_world: DemoWorld
) -> None:
    headers = _patient_headers(api)

    withdrawn = api.post(
        WITHDRAW, headers=headers, json={"scope": "SENSITIVE_DATA_PROCESSING"}
    )
    blocked = api.post(REQUESTS, headers=headers, json={"request_type": "ACCESS"})

    assert withdrawn.status_code == 200
    assert withdrawn.json()["consent_required"] is True
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_a_privacy_request_runs_from_open_to_an_audited_export(
    api: TestClient, demo_world: DemoWorld
) -> None:
    patient = _patient_headers(api)
    admin = _staff_headers(api, ADMIN_EMAIL)

    created = api.post(REQUESTS, headers=patient, json={"request_type": "ACCESS"})
    request_id = created.json()["id"]
    before = api.get(f"{REQUESTS}/{request_id}/export", headers=patient)
    resolved = api.post(
        f"{REQUESTS}/{request_id}/resolve",
        headers=admin,
        json={"decision": "APPROVE", "note": NOTE},
    )
    exported = api.get(f"{REQUESTS}/{request_id}/export", headers=patient)

    assert created.status_code == 201
    assert created.json()["status"] == "OPEN"
    assert before.status_code == 409
    assert resolved.json()["status"] == "APPROVED"
    assert exported.status_code == 200
    assert exported.json()["patient_id"] is not None
    assert UUID(exported.json()["request_id"]) == UUID(request_id)


def test_the_administrator_sees_the_standing_without_clinical_data(
    api: TestClient, demo_world: DemoWorld
) -> None:
    admin = _staff_headers(api, ADMIN_EMAIL)

    response = api.get("/api/v1/consents", headers=admin)

    assert response.status_code == 200
    items = response.json()["items"]
    assert "GRANTED" in {item["standing"] for item in items}
    for item in items:
        assert set(item) == {
            "patient_id",
            "standing",
            "privacy_notice_version_id",
            "occurred_at",
        }
