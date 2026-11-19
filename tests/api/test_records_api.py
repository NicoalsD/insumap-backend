"""Patient record endpoints over the real app with port doubles (API.md 8.6)."""

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

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

PATIENT_EMAIL = "paciente@example.test"
DOCTOR = UUID(int=910)
OTHER_PATIENT = UUID(int=999)
BASE = "/api/v1/readings"
PATIENT_PERMISSIONS = frozenset(
    {
        PermissionCode.GLUCOSE_WRITE_OWN,
        PermissionCode.GLUCOSE_READ_OWN,
        PermissionCode.RECORDS_WRITE_OWN,
        PermissionCode.RECORDS_READ_OWN,
    }
)
DOCTOR_PERMISSIONS = frozenset({PermissionCode.PATIENTS_READ_ASSIGNED})


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PATIENT_PERMISSIONS
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=911),
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
    api.records.patients.assigned.add((DOCTOR, PATIENT_ID))
    return api


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def reading(api: IdentityApi, client_id: UUID, value: float = 112) -> dict[str, Any]:
    measured_at = api.world.clock.now() - timedelta(hours=1)
    return {
        "client_reading_id": str(client_id),
        "value": value,
        "unit": "mg/dL",
        "measured_at": measured_at.isoformat(),
        "source": "MANUAL",
    }


def test_patient_records_a_reading_and_lists_it(api: IdentityApi) -> None:
    headers = patient(api)
    client_id = UUID(int=1)

    created = api.client.post(BASE, headers=headers, json=reading(api, client_id))
    listed = api.client.get(BASE, headers=headers)

    assert created.status_code == 201, created.text
    assert created.headers["Location"].endswith(created.json()["id"])
    assert Decimal(created.json()["value_mg_dl"]) == Decimal(112)
    assert listed.status_code == 200
    assert [item["client_reading_id"] for item in listed.json()["items"]] == [
        str(client_id)
    ]


def test_repeating_the_same_reading_answers_200_and_does_not_duplicate(
    api: IdentityApi,
) -> None:
    headers = patient(api)
    body = reading(api, UUID(int=2))

    first = api.client.post(BASE, headers=headers, json=body)
    second = api.client.post(BASE, headers=headers, json=body)
    listed = api.client.get(BASE, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert len(listed.json()["items"]) == 1


def test_same_client_id_with_other_content_is_409(api: IdentityApi) -> None:
    headers = patient(api)
    client_id = UUID(int=3)
    api.client.post(BASE, headers=headers, json=reading(api, client_id, 112))

    response = api.client.post(BASE, headers=headers, json=reading(api, client_id, 140))

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"


def test_batch_saves_the_valid_items_and_reports_the_rejected_one(
    api: IdentityApi,
) -> None:
    headers = patient(api)

    response = api.client.post(
        f"{BASE}/batch",
        headers=headers,
        json={
            "items": [
                reading(api, UUID(int=4), 112),
                reading(api, UUID(int=5), 5),
            ]
        },
    )

    assert response.status_code == 200, response.text
    valid, rejected = response.json()["items"]
    assert valid["result"] == "CREATED"
    assert valid["reading_id"] is not None
    assert rejected["result"] == "REJECTED"
    assert rejected["reason_code"] == "GLUCOSE_OUT_OF_RANGE"
    listed = api.client.get(BASE, headers=headers).json()
    assert len(listed["items"]) == 1


def test_without_token_is_401(api: IdentityApi) -> None:
    assert api.client.get(BASE).status_code == 401
    assert api.client.post(BASE, json=reading(api, UUID(int=6))).status_code == 401


def test_without_permission_is_403(api: IdentityApi) -> None:
    api.world.permissions.by_role[Role.PATIENT] = frozenset()
    headers = patient(api)

    response = api.client.post(BASE, headers=headers, json=reading(api, UUID(int=7)))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_doctor_reads_an_assigned_patient(api: IdentityApi) -> None:
    headers = api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))

    response = api.client.get(
        f"/api/v1/patients/{PATIENT_ID}/readings", headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_doctor_reading_a_patient_not_assigned_is_404_like_a_missing_one(
    api: IdentityApi,
) -> None:
    headers = api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))

    not_assigned = api.client.get(
        f"/api/v1/patients/{OTHER_PATIENT}/readings", headers=headers
    )
    missing = api.client.get(
        f"/api/v1/patients/{UUID(int=12345)}/readings", headers=headers
    )

    assert not_assigned.status_code == missing.status_code == 404
    assert not_assigned.json() == missing.json()


def test_unknown_field_is_422(api: IdentityApi) -> None:
    headers = patient(api)
    body = reading(api, UUID(int=8))
    body["clinic_id"] = str(CLINIC.clinic_id)

    response = api.client.post(BASE, headers=headers, json=body)

    assert response.status_code == 422, response.text
