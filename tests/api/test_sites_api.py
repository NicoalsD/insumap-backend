"""Site endpoints over the real app with port doubles (API.md 8.3, RF-15)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from insumap.domain.clinic.site import Site
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.field_limits import FieldLimits
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import CLINIC

ADMIN = UUID(int=900)
DOCTOR = UUID(int=901)
OTHER_CLINIC = UUID(int=777)
NORTH = UUID(int=800)
SOUTH = UUID(int=801)
FOREIGN = UUID(int=802)
MISSING = UUID(int=899)
BASE = "/api/v1/sites"
ADMIN_PERMISSIONS = frozenset({PermissionCode.SITES_MANAGE})
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def site(site_id: UUID, name: str, clinic: UUID = CLINIC.clinic_id) -> Site:
    return Site(
        site_id=site_id,
        clinic_id=clinic,
        name=name,
        clinic_is_demo=True,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.sites.sites = {
        NORTH: site(NORTH, "Sede Norte"),
        SOUTH: site(SOUTH, "Sede Sur"),
        FOREIGN: site(FOREIGN, "Sede Ajena", clinic=OTHER_CLINIC),
    }
    api.sites.add_staff(DOCTOR, CLINIC.clinic_id, NORTH)
    return api


def _payload(body: dict[str, Any] | None) -> dict[str, Any]:
    """A JSON body, or none: the test client's ``get`` takes no body."""
    return {} if body is None else {"json": body}


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def test_create_returns_the_site_with_the_simulated_flag(api: IdentityApi) -> None:
    response = api.client.post(
        BASE, headers=admin(api), json={"name": "  Sede Oriente "}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Sede Oriente"
    assert body["simulated"] is True
    assert set(body) == {"id", "name", "simulated"}
    assert [entry.action for entry in api.audit_log.entries] == ["SITE_CREATED"]


def test_create_refuses_a_name_already_taken(api: IdentityApi) -> None:
    response = api.client.post(BASE, headers=admin(api), json={"name": "sede NORTE"})

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"


def test_listing_is_paginated_and_only_shows_the_clinic(api: IdentityApi) -> None:
    headers = admin(api)

    first = api.client.get(BASE, headers=headers, params={"limit": 1})
    second = api.client.get(
        BASE,
        headers=headers,
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )

    assert first.status_code == 200, first.text
    assert [item["id"] for item in first.json()["items"]] == [str(NORTH)]
    assert [item["id"] for item in second.json()["items"]] == [str(SOUTH)]
    assert second.json()["next_cursor"] is None
    assert str(FOREIGN) not in first.text + second.text


def test_rename_returns_the_updated_site(api: IdentityApi) -> None:
    response = api.client.patch(
        f"{BASE}/{NORTH}", headers=admin(api), json={"name": "Norte Dos"}
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": str(NORTH),
        "name": "Norte Dos",
        "simulated": True,
    }


def test_another_clinics_site_and_a_missing_one_answer_the_same_404(
    api: IdentityApi,
) -> None:
    headers = admin(api)

    foreign = api.client.patch(
        f"{BASE}/{FOREIGN}", headers=headers, json={"name": "Robada"}
    )
    missing = api.client.patch(
        f"{BASE}/{MISSING}", headers=headers, json={"name": "Robada"}
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert api.sites.sites[FOREIGN].name == "Sede Ajena"


def test_set_user_sites_replaces_the_list_and_returns_the_staff(
    api: IdentityApi,
) -> None:
    response = api.client.put(
        f"/api/v1/users/{DOCTOR}/sites",
        headers=admin(api),
        json={"site_ids": [str(SOUTH), str(SOUTH)]},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "user_id": str(DOCTOR),
        "site_ids": [str(SOUTH)],
        "simulated": True,
    }


def test_set_user_sites_refuses_a_site_of_another_clinic(api: IdentityApi) -> None:
    response = api.client.put(
        f"/api/v1/users/{DOCTOR}/sites",
        headers=admin(api),
        json={"site_ids": [str(FOREIGN)]},
    )
    unknown_user = api.client.put(
        f"/api/v1/users/{MISSING}/sites", headers=admin(api), json={"site_ids": []}
    )

    assert response.status_code == 404
    assert response.json() == unknown_user.json()
    assert api.sites.staff[DOCTOR].site_ids == frozenset({NORTH})


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", BASE, {"name": "Sede Oriente"}),
        ("get", BASE, None),
        ("patch", f"{BASE}/{NORTH}", {"name": "Norte"}),
        ("put", f"/api/v1/users/{DOCTOR}/sites", {"site_ids": []}),
    ],
)
def test_every_route_needs_a_token(
    api: IdentityApi, method: str, path: str, body: dict[str, Any] | None
) -> None:
    response = getattr(api.client, method)(path, **_payload(body))

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", BASE, {"name": "Sede Oriente"}),
        ("get", BASE, None),
        ("patch", f"{BASE}/{NORTH}", {"name": "Norte"}),
        ("put", f"/api/v1/users/{DOCTOR}/sites", {"site_ids": []}),
    ],
)
def test_every_route_needs_the_sites_permission(
    api: IdentityApi, method: str, path: str, body: dict[str, Any] | None
) -> None:
    token = api.staff_token(ADMIN, Role.CLINIC_ADMIN, frozenset())

    response = getattr(api.client, method)(
        path, headers=api.bearer(token), **_payload(body)
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", BASE, {"name": "Sede Oriente", "address": "Calle 1"}),
        ("post", BASE, {"name": "   "}),
        ("post", BASE, {"name": "x" * (FieldLimits.SITE_NAME_MAX_LENGTH + 1)}),
        ("patch", f"{BASE}/{NORTH}", {"name": "Norte", "is_active": False}),
        ("put", f"/api/v1/users/{DOCTOR}/sites", {"site_ids": ["no-es-uuid"]}),
        ("put", f"/api/v1/users/{DOCTOR}/sites", {"site_ids": [], "extra": 1}),
    ],
)
def test_invalid_or_unknown_fields_are_422(
    api: IdentityApi, method: str, path: str, body: dict[str, Any]
) -> None:
    response = getattr(api.client, method)(path, headers=admin(api), json=body)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_a_staff_list_over_the_limit_is_422(api: IdentityApi) -> None:
    too_many = [
        str(UUID(int=5000 + n)) for n in range(FieldLimits.STAFF_SITES_MAX_ITEMS + 1)
    ]

    response = api.client.put(
        f"/api/v1/users/{DOCTOR}/sites",
        headers=admin(api),
        json={"site_ids": too_many},
    )

    assert response.status_code == 422, response.text
