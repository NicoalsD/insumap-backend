"""Target profile endpoints over the real app with port doubles (API.md 8.7)."""

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
    PATIENT_ID,
    PATIENT_USER,
)

ADMIN = UUID(int=900)
DOCTOR = UUID(int=910)
STRANGER_PATIENT = UUID(int=999)
BASE = "/api/v1/target-profiles"
CHANGE_REASON = "Ajuste aprobado por el comité de la clínica"
ADMIN_PERMISSIONS = frozenset({PermissionCode.TARGET_PROFILES_MANAGE})
DOCTOR_PERMISSIONS = frozenset(
    {PermissionCode.TARGET_PROFILES_ASSIGN, PermissionCode.TARGET_PROFILES_MANAGE}
)
DOCTOR_ASSIGN_ONLY = frozenset({PermissionCode.TARGET_PROFILES_ASSIGN})


def profile_body(code: str = "CLINIC_TARGETS", **overrides: Any) -> dict[str, Any]:
    """A full profile. The numbers are fixtures, not clinical rules."""
    body: dict[str, Any] = {
        "code": code,
        "label": "Metas de la clínica",
        "population": "ADULT",
        "is_default": True,
        "range_low_mg_dl": 70,
        "range_high_mg_dl": 180,
        "very_low_mg_dl": 54,
        "very_high_mg_dl": 250,
        "tir_min_pct": 70,
        "tbr_l1_max_pct": 4,
        "tbr_l2_max_pct": 1,
        "tar_l1_max_pct": 25,
        "tar_l2_max_pct": 5,
        "cv_max_pct": 36,
        "min_data_sufficiency_pct": 70,
        "min_days": 14,
        "max_gap_minutes": 15,
        "hypo_episode_min_minutes": 15,
        "min_readings_for_cv": 100,
        "min_readings_for_cv_smbg": 3,
        "night_start": "00:00",
        "night_end": "06:00",
        "source_reference": "Consenso de prueba, tabla 1",
    }
    body.update(overrides)
    return body


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
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


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))


def create_profile(api: IdentityApi, code: str = "CLINIC_TARGETS") -> dict[str, Any]:
    response = api.client.post(BASE, headers=admin(api), json=profile_body(code))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_admin_creates_an_active_version_one_and_it_is_listed(api: IdentityApi) -> None:
    headers = admin(api)

    created = api.client.post(BASE, headers=headers, json=profile_body())
    listed = api.client.get(BASE, headers=headers)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "CLINIC_TARGETS"
    assert body["version"] == 1
    assert body["status"] == "ACTIVE"
    assert body["tir_min_pct"] == 70.0
    assert body["night_end"] == "06:00:00"
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]
    assert [e.action for e in api.audit_log.entries] == ["TARGET_PROFILE_CREATED"]


def test_unknown_field_is_a_validation_error(api: IdentityApi) -> None:
    response = api.client.post(
        BASE, headers=admin(api), json=profile_body(unknown_field=1)
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_range_out_of_order_lists_the_broken_rule(api: IdentityApi) -> None:
    response = api.client.post(
        BASE,
        headers=admin(api),
        json=profile_body(range_high_mg_dl=60),
    )

    assert response.status_code == 422
    errors = response.json()["error"]["detail"]["errors"]
    assert {"field": "body.range_high_mg_dl", "type": "invalid_order"} in errors
    assert api.catalog.profiles == {}


def test_percentage_above_one_hundred_is_refused_before_the_domain(
    api: IdentityApi,
) -> None:
    response = api.client.post(
        BASE, headers=admin(api), json=profile_body(tir_min_pct=101)
    )

    assert response.status_code == 422


def test_a_repeated_code_is_a_conflict(api: IdentityApi) -> None:
    create_profile(api)

    response = api.client.post(BASE, headers=admin(api), json=profile_body())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_no_token_is_unauthenticated(api: IdentityApi) -> None:
    response = api.client.get(BASE)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_doctor_without_the_manage_permission_cannot_create(api: IdentityApi) -> None:
    headers = api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_ASSIGN_ONLY))

    response = api.client.post(BASE, headers=headers, json=profile_body())

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_doctor_reads_the_catalog_with_the_assign_permission(
    api: IdentityApi,
) -> None:
    created = create_profile(api)
    headers = api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_ASSIGN_ONLY))

    response = api.client.get(f"{BASE}/{created['id']}", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["versions"][0]["version"] == 1


def test_get_profile_shows_the_history_after_a_new_version(api: IdentityApi) -> None:
    created = create_profile(api)
    headers = admin(api)
    version = api.client.post(
        f"{BASE}/{created['id']}/versions",
        headers=headers,
        json={"tir_min_pct": 75, "change_reason": CHANGE_REASON},
    )

    detail = api.client.get(f"{BASE}/{created['id']}", headers=headers)

    assert version.status_code == 201, version.text
    assert version.json()["version"] == 2
    assert version.json()["tir_min_pct"] == 75.0
    history = [(v["version"], v["status"]) for v in detail.json()["versions"]]
    assert history == [(1, "RETIRED"), (2, "ACTIVE")]


def test_version_needs_a_reason_and_at_least_one_change(api: IdentityApi) -> None:
    created = create_profile(api)
    headers = admin(api)

    without_reason = api.client.post(
        f"{BASE}/{created['id']}/versions",
        headers=headers,
        json={"tir_min_pct": 75},
    )
    without_change = api.client.post(
        f"{BASE}/{created['id']}/versions",
        headers=headers,
        json={"change_reason": CHANGE_REASON},
    )

    assert without_reason.status_code == 422
    assert without_change.status_code == 422


def test_version_of_an_unknown_profile_is_not_found(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/{UUID(int=4242)}/versions",
        headers=admin(api),
        json={"tir_min_pct": 75, "change_reason": CHANGE_REASON},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_doctor_assigns_a_profile_to_his_patient_and_it_is_audited(
    api: IdentityApi,
) -> None:
    profile = create_profile(api)

    response = api.client.put(
        f"/api/v1/patients/{PATIENT_ID}/target-profile",
        headers=doctor(api),
        json={"target_profile_id": profile["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["target_profile_id"] == profile["id"]
    assert response.json()["patient_id"] == str(PATIENT_ID)
    assert "TARGET_PROFILE_ASSIGNED" in [e.action for e in api.audit_log.entries]


def test_assigning_to_an_unassigned_patient_is_not_found(api: IdentityApi) -> None:
    profile = create_profile(api)

    stranger = api.client.put(
        f"/api/v1/patients/{STRANGER_PATIENT}/target-profile",
        headers=doctor(api),
        json={"target_profile_id": profile["id"]},
    )
    missing = api.client.put(
        f"/api/v1/patients/{UUID(int=5555)}/target-profile",
        headers=doctor(api),
        json={"target_profile_id": profile["id"]},
    )

    assert stranger.status_code == 404
    assert missing.status_code == 404
    assert stranger.json() == missing.json()


def test_assigning_a_retired_profile_is_a_conflict(api: IdentityApi) -> None:
    profile = create_profile(api)
    api.client.post(
        f"{BASE}/{profile['id']}/versions",
        headers=admin(api),
        json={"tir_min_pct": 75, "change_reason": CHANGE_REASON},
    )

    response = api.client.put(
        f"/api/v1/patients/{PATIENT_ID}/target-profile",
        headers=doctor(api),
        json={"target_profile_id": profile["id"]},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_admin_cannot_assign_a_profile_to_a_patient(api: IdentityApi) -> None:
    profile = create_profile(api)

    response = api.client.put(
        f"/api/v1/patients/{PATIENT_ID}/target-profile",
        headers=admin(api),
        json={"target_profile_id": profile["id"]},
    )

    assert response.status_code == 403
