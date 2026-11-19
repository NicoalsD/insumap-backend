"""Care team endpoints over the real app with port doubles (API.md 8.5)."""

from typing import Any
from uuid import UUID

import pytest

from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.access_fakes import PATIENT

ADMIN = UUID(int=900)
DOCTOR_A = UUID(int=901)
DOCTOR_B = UUID(int=902)
OTHER_CLINIC_PATIENT = UUID(int=999)
BASE = "/api/v1/care-team/assignments"
REASON = "Cambio de turno del médico tratante"
ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.CARE_TEAM_ASSIGN, PermissionCode.CARE_TEAM_READ}
)


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.staff.doctors.update({DOCTOR_A, DOCTOR_B})
    return api


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def assign(api: IdentityApi, headers: dict[str, str], doctor: UUID) -> Any:
    return api.client.post(
        BASE,
        headers=headers,
        json={"patient_id": str(PATIENT), "doctor_id": str(doctor)},
    )


def test_first_doctor_is_primary_and_is_audited(api: IdentityApi) -> None:
    headers = admin(api)

    response = assign(api, headers, DOCTOR_A)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["doctor_id"] == str(DOCTOR_A)
    assert body["is_primary"] is True
    assert body["ended_at"] is None
    assert [entry.action for entry in api.audit_log.entries] == ["DOCTOR_ASSIGNED"]


def test_make_primary_reassign_and_end(api: IdentityApi) -> None:
    headers = admin(api)
    first = assign(api, headers, DOCTOR_A).json()
    second = assign(api, headers, DOCTOR_B).json()

    primary = api.client.post(f"{BASE}/{second['id']}/make-primary", headers=headers)
    ended = api.client.post(
        f"{BASE}/{first['id']}/end", headers=headers, json={"reason": REASON}
    )

    assert primary.status_code == 200, primary.text
    assert primary.json()["is_primary"] is True
    assert ended.status_code == 200, ended.text
    assert ended.json()["end_reason"] == REASON
    history = api.client.get(BASE, headers=headers, params={"status": "ENDED"})
    assert [a["id"] for a in history.json()["items"]] == [first["id"]]


def test_reassign_creates_the_new_assignment(api: IdentityApi) -> None:
    headers = admin(api)
    first = assign(api, headers, DOCTOR_A).json()

    response = api.client.post(
        f"{BASE}/{first['id']}/reassign",
        headers=headers,
        json={"new_doctor_id": str(DOCTOR_B), "reason": REASON},
    )

    assert response.status_code == 201, response.text
    assert response.json()["doctor_id"] == str(DOCTOR_B)
    assert response.json()["is_primary"] is True


def test_listing_is_paginated(api: IdentityApi) -> None:
    headers = admin(api)
    assign(api, headers, DOCTOR_A)
    assign(api, headers, DOCTOR_B)

    first = api.client.get(BASE, headers=headers, params={"limit": 1})
    second = api.client.get(
        BASE,
        headers=headers,
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )

    assert first.status_code == 200
    assert len(first.json()["items"]) == 1
    assert second.json()["next_cursor"] is None
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]


def test_unknown_patient_or_doctor_is_404(api: IdentityApi) -> None:
    headers = admin(api)

    other = api.client.post(
        BASE,
        headers=headers,
        json={"patient_id": str(OTHER_CLINIC_PATIENT), "doctor_id": str(DOCTOR_A)},
    )
    not_doctor = assign(api, headers, UUID(int=12345))

    assert other.status_code == not_doctor.status_code == 404
    assert other.json() == not_doctor.json()


def test_end_without_reason_is_422(api: IdentityApi) -> None:
    headers = admin(api)
    first = assign(api, headers, DOCTOR_A).json()

    response = api.client.post(
        f"{BASE}/{first['id']}/end", headers=headers, json={"reason": "corto"}
    )

    assert response.status_code == 422


def test_without_token_is_401(api: IdentityApi) -> None:
    assert api.client.get(BASE).status_code == 401


def test_without_permission_is_403(api: IdentityApi) -> None:
    token = api.staff_token(DOCTOR_A, Role.DOCTOR, frozenset())

    response = assign(api, api.bearer(token), DOCTOR_B)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_doctor_lists_only_his_assignments(api: IdentityApi) -> None:
    headers = admin(api)
    assign(api, headers, DOCTOR_A)
    assign(api, headers, DOCTOR_B)
    doctor = api.bearer(
        api.staff_token(
            DOCTOR_A, Role.DOCTOR, frozenset({PermissionCode.CARE_TEAM_READ})
        )
    )

    response = api.client.get(BASE, headers=doctor)

    assert response.status_code == 200
    assert {a["doctor_id"] for a in response.json()["items"]} == {str(DOCTOR_A)}


def test_unknown_field_is_422(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(
        BASE,
        headers=headers,
        json={
            "patient_id": str(PATIENT),
            "doctor_id": str(DOCTOR_A),
            "clinic_id": str(UUID(int=1)),
        },
    )

    assert response.status_code == 422
