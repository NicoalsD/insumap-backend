"""Injection sites and the lipohypertrophy symptom over HTTP (API.md 8.6)."""

from __future__ import annotations

from datetime import timedelta
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
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)

PATIENT_EMAIL = "paciente@example.test"
SITES = "/api/v1/patients/own/injection-sites"
PERMISSIONS = frozenset(
    {PermissionCode.RECORDS_WRITE_OWN, PermissionCode.RECORDS_READ_OWN}
)
FORBIDDEN_KEYS = {"units", "dose", "dose_units", "units_suggested"}


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PERMISSIONS
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=941),
                clinic_id=CLINIC.clinic_id,
                patient_id=PATIENT_ID,
                privacy_notice_version_id=NOTICE_ID,
                scope=ConsentScope.SENSITIVE_DATA_PROCESSING,
                action=ConsentAction.ACCEPTED,
                occurred_at=api.world.clock.now(),
                recorded_by=PATIENT_USER,
            )
        ]
    )
    return api


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def keys_of(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


def test_the_answer_has_a_suggestion_eight_sites_and_the_rules_version(
    api: IdentityApi,
) -> None:
    response = api.client.get(SITES, params={"kind": "BOLUS"}, headers=patient(api))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "BOLUS"
    assert body["rules_version"] == "injection-rules-1"
    assert body["suggestion"]["site"] == "ABDOMEN_RIGHT"
    assert body["suggestion"]["spot"] == 1
    assert body["suggestion"]["needle_note"] == "NEEDLE_4MM_PINCH_OPTIONAL"
    assert len(body["sites"]) == 8
    assert {"site", "state", "reason_code", "last_used_at", "last_spot"} == set(
        body["sites"][0]
    )


def test_the_answer_never_carries_a_unit_of_insulin(api: IdentityApi) -> None:
    for kind in ("BASAL", "BOLUS", "CORRECTION", "MIXED"):
        response = api.client.get(SITES, params={"kind": kind}, headers=patient(api))
        assert not keys_of(response.json()) & FORBIDDEN_KEYS


def test_a_missing_or_unknown_kind_is_422(api: IdentityApi) -> None:
    headers = patient(api)

    assert api.client.get(SITES, headers=headers).status_code == 422
    assert (
        api.client.get(SITES, params={"kind": "X"}, headers=headers).status_code == 422
    )


def test_without_token_is_401(api: IdentityApi) -> None:
    assert api.client.get(SITES, params={"kind": "BASAL"}).status_code == 401


def test_without_permission_is_403(api: IdentityApi) -> None:
    api.world.permissions.by_role[Role.PATIENT] = frozenset()

    response = api.client.get(SITES, params={"kind": "BASAL"}, headers=patient(api))

    assert response.status_code == 403


def test_the_route_is_not_taken_by_the_patient_id_routes(api: IdentityApi) -> None:
    response = api.client.get(SITES, params={"kind": "BASAL"}, headers=patient(api))

    assert response.status_code != 404
    assert response.headers["content-type"].startswith("application/json")
    assert "suggestion" in response.json()


def symptom(code: str, site: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "symptom_code": code,
        "occurred_at": (api_clock() - timedelta(hours=1)).isoformat(),
    }
    if site is not None:
        body["injection_site"] = site
    return body


_CLOCK: list[Any] = []


def api_clock() -> Any:
    return _CLOCK[0]


@pytest.fixture(autouse=True)
def _remember_clock(api: IdentityApi) -> None:
    _CLOCK[:] = [api.world.clock.now()]


def test_lipohypertrophy_needs_a_site(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/symptoms", headers=patient(api), json=symptom("LIPOHYPERTROPHY")
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["detail"]["errors"][0]["field"] == (
        "body.injection_site"
    )


def test_lipohypertrophy_with_a_site_is_recorded_and_returned(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/symptoms",
        headers=patient(api),
        json=symptom("LIPOHYPERTROPHY", "THIGH_RIGHT"),
    )

    assert response.status_code == 201, response.text
    assert response.json()["injection_site"] == "THIGH_RIGHT"


def test_another_symptom_needs_no_site(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/symptoms", headers=patient(api), json=symptom("THIRST")
    )

    assert response.status_code == 201, response.text
    assert response.json()["injection_site"] is None


def test_an_unknown_site_in_a_symptom_is_422(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/symptoms",
        headers=patient(api),
        json=symptom("LIPOHYPERTROPHY", "CHEST_LEFT"),
    )

    assert response.status_code == 422
