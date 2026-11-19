"""Clinic endpoints over the real app with port doubles (API.md 8.3)."""

from typing import Any
from uuid import UUID

import pytest

from insumap.domain.clinic.clinic import Clinic
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import NOW

BASE = "/api/v1/clinics"
PLATFORM = UUID(int=800)
CLINIC_ADMIN = UUID(int=801)
DEMO_CLINIC = UUID(int=10)
UNKNOWN_CLINIC = UUID(int=999)
REASON = "Revisión de contrato con la clínica"
PLATFORM_PERMISSIONS = frozenset({PermissionCode.CLINICS_MANAGE})
STAFF_PERMISSIONS = frozenset({PermissionCode.CLINICS_READ})


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.clinics.add(
        Clinic.create(
            clinic_id=DEMO_CLINIC,
            name="Clínica Demo",
            tax_id="900000000-1",
            timezone="America/Bogota",
            is_demo=True,
            at=NOW,
        )
    )
    return api


def platform(api: IdentityApi) -> dict[str, str]:
    return api.bearer(
        api.staff_token(PLATFORM, Role.PLATFORM_ADMIN, PLATFORM_PERMISSIONS)
    )


def staff(api: IdentityApi) -> dict[str, str]:
    return api.bearer(
        api.staff_token(CLINIC_ADMIN, Role.CLINIC_ADMIN, STAFF_PERMISSIONS)
    )


def create(api: IdentityApi, headers: dict[str, str], **fields: Any) -> Any:
    body = {"name": "Clínica Norte", "tax_id": "900000001"} | fields
    return api.client.post(BASE, headers=headers, json=body)


def test_platform_creates_an_active_clinic_and_audits_it(api: IdentityApi) -> None:
    response = create(api, platform(api))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["timezone"] == "America/Bogota"
    assert body["is_demo"] is False
    assert body["simulated"] is False
    assert "suspended_at" not in body
    [entry] = [e for e in api.audit_log.entries if e.action == "CLINIC_CREATED"]
    assert str(entry.clinic_id) == body["id"]


def test_a_repeated_name_ignoring_case_is_409(api: IdentityApi) -> None:
    headers = platform(api)
    assert create(api, headers, name="Clínica Norte").status_code == 201

    response = create(api, headers, name="CLÍNICA NORTE")

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"


def test_unknown_field_is_422(api: IdentityApi) -> None:
    response = create(api, platform(api), status="SUSPENDED")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_timezone_is_422(api: IdentityApi) -> None:
    response = create(api, platform(api), timezone="Mars/Olympus")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_clinic_staff_cannot_create_a_clinic_403(api: IdentityApi) -> None:
    response = create(api, staff(api))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_without_a_token_every_clinic_route_is_401(api: IdentityApi) -> None:
    assert api.client.get(BASE).status_code == 401
    assert api.client.post(BASE, json={}).status_code == 401
    assert api.client.get(f"{BASE}/current").status_code == 401


def test_listing_is_paginated(api: IdentityApi) -> None:
    headers = platform(api)
    create(api, headers, name="Clínica Norte")
    create(api, headers, name="Clínica Sur")

    first = api.client.get(BASE, headers=headers, params={"limit": 2})
    second = api.client.get(
        BASE,
        headers=headers,
        params={"limit": 2, "cursor": first.json()["next_cursor"]},
    )

    assert first.status_code == 200, first.text
    assert len(first.json()["items"]) == 2
    assert first.json()["next_cursor"] is not None
    assert len(second.json()["items"]) == 1
    assert second.json()["next_cursor"] is None


def test_listing_filters_by_status(api: IdentityApi) -> None:
    headers = platform(api)
    norte = create(api, headers, name="Clínica Norte").json()
    api.client.post(
        f"{BASE}/{norte['id']}/suspend", headers=headers, json={"reason": REASON}
    )

    response = api.client.get(BASE, headers=headers, params={"status": "SUSPENDED"})

    assert response.status_code == 200, response.text
    assert [c["id"] for c in response.json()["items"]] == [norte["id"]]


def test_get_shows_the_suspension_and_its_reason(api: IdentityApi) -> None:
    headers = platform(api)
    api.client.post(
        f"{BASE}/{DEMO_CLINIC}/suspend", headers=headers, json={"reason": REASON}
    )

    response = api.client.get(f"{BASE}/{DEMO_CLINIC}", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUSPENDED"
    assert body["suspended_reason"] == REASON
    assert body["suspended_at"] is not None


def test_unknown_clinic_is_404(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE}/{UNKNOWN_CLINIC}", headers=platform(api))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_malformed_clinic_id_is_422(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE}/no-es-un-uuid", headers=platform(api))

    assert response.status_code == 422


def test_update_changes_only_the_fields_sent(api: IdentityApi) -> None:
    headers = platform(api)

    response = api.client.patch(
        f"{BASE}/{DEMO_CLINIC}", headers=headers, json={"is_demo": False}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_demo"] is False
    assert body["simulated"] is False
    assert body["name"] == "Clínica Demo"
    [entry] = [e for e in api.audit_log.entries if e.action == "CLINIC_UPDATED"]
    assert entry.changed_fields == ("is_demo",)


def test_update_with_an_unknown_field_is_422(api: IdentityApi) -> None:
    response = api.client.patch(
        f"{BASE}/{DEMO_CLINIC}", headers=platform(api), json={"status": "ACTIVE"}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("body", [{}, {"reason": "corto"}])
def test_suspend_without_a_valid_reason_is_reason_required(
    api: IdentityApi, body: dict[str, str]
) -> None:
    response = api.client.post(
        f"{BASE}/{DEMO_CLINIC}/suspend", headers=platform(api), json=body
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REASON_REQUIRED"


def test_suspending_twice_is_an_invalid_transition(api: IdentityApi) -> None:
    headers = platform(api)
    url = f"{BASE}/{DEMO_CLINIC}/suspend"
    assert (
        api.client.post(url, headers=headers, json={"reason": REASON}).status_code
        == 200
    )

    response = api.client.post(url, headers=headers, json={"reason": REASON})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_reactivate_lifts_the_suspension(api: IdentityApi) -> None:
    headers = platform(api)
    api.client.post(
        f"{BASE}/{DEMO_CLINIC}/suspend", headers=headers, json={"reason": REASON}
    )

    response = api.client.post(f"{BASE}/{DEMO_CLINIC}/reactivate", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["suspended_at"] is None
    assert body["suspended_reason"] is None


def test_reactivating_an_active_clinic_is_409(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/{DEMO_CLINIC}/reactivate", headers=platform(api)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_clinic_staff_reads_their_own_clinic(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE}/current", headers=staff(api))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(DEMO_CLINIC)
    assert body["simulated"] is True
    assert body["timezone"] == "America/Bogota"
    assert "tax_id" not in body


def test_platform_admin_has_no_clinic_to_read_403(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE}/current", headers=platform(api))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_listing_is_refused_to_clinic_staff_403(api: IdentityApi) -> None:
    response = api.client.get(BASE, headers=staff(api))

    assert response.status_code == 403
