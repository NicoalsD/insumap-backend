"""Treatment plans and protocol templates over the real app (API.md 8.7)."""

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.monitoring.injection_sites import SiteCode
from insumap.domain.treatment.plan import PlanStatus
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import (
    CLINIC,
    NOTICE_ID,
    NOW,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)
from tests.support.treatment_fakes import active
from tests.unit.domain.treatment.factories import draft, insulin, plan_items

DOCTOR = UUID(int=930)
ADMIN = UUID(int=931)
OTHER_PATIENT = UUID(int=999)
PATIENT_EMAIL = "paciente@example.test"
BASE = "/api/v1"
PLANS = f"{BASE}/treatment-plans"
TEMPLATES = f"{BASE}/protocol-templates"
OWN_PLAN = f"{BASE}/patients/own/treatment-plan"
DOCTOR_PERMISSIONS = frozenset(
    {PermissionCode.TREATMENT_PLANS_MANAGE, PermissionCode.PROTOCOL_TEMPLATES_READ}
)
ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.PROTOCOL_TEMPLATES_MANAGE, PermissionCode.PROTOCOL_TEMPLATES_READ}
)
PATIENT_PERMISSIONS = frozenset({PermissionCode.TREATMENT_PLANS_READ_OWN})
ITEM = {
    "item_type": "INSULIN",
    "name": "Basal",
    "insulin_kind": "BASAL",
    "dose_units": "10",
    "time_of_day": "08:00:00",
}
CONTENT = {"items": [ITEM]}


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PATIENT_PERMISSIONS
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=933),
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


def doctor(
    api: IdentityApi, permissions: frozenset[PermissionCode] = DOCTOR_PERMISSIONS
) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, permissions))


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def create_plan(api: IdentityApi, headers: dict[str, str], **extra: Any) -> Any:
    body = {"patient_id": str(PATIENT_ID), "content": CONTENT, **extra}
    return api.client.post(PLANS, headers=headers, json=body)


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def add_active_plan(api: IdentityApi) -> UUID:
    plan_id = UUID(int=6001)
    row = active(
        replace(
            draft(*plan_items(insulin())),
            plan_id=plan_id,
            patient_id=PATIENT_ID,
            clinic_id=CLINIC.clinic_id,
        )
    )
    api.plans.rows[plan_id] = row
    return plan_id


# Plans: the doctor's decisions.


def test_a_doctor_creates_a_draft_for_an_assigned_patient(api: IdentityApi) -> None:
    response = create_plan(api, doctor(api))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["version"] == 1
    assert body["patient_id"] == str(PATIENT_ID)
    assert body["items"][0]["name"] == "Basal"
    # The test clinic is the demo clinic, so its resources say they are simulated.
    assert body["simulated"] is True


def test_the_draft_is_activated_and_its_predecessor_superseded(
    api: IdentityApi,
) -> None:
    headers = doctor(api)
    plan_id = create_plan(api, headers).json()["id"]

    activated = api.client.post(f"{PLANS}/{plan_id}/activate", headers=headers)

    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE"


def test_activation_refuses_an_invalid_draft_with_each_violation(
    api: IdentityApi,
) -> None:
    headers = doctor(api)
    plan_id = create_plan(api, headers, content={"items": []}).json()["id"]

    response = api.client.post(f"{PLANS}/{plan_id}/activate", headers=headers)

    assert response.status_code == 422, response.text
    assert error_code(response) == "VALIDATION_ERROR"
    assert response.json()["error"]["detail"]["errors"] == [
        {"field": "items", "type": "empty_plan"}
    ]


def test_a_draft_is_edited_and_the_old_content_is_kept_as_a_snapshot(
    api: IdentityApi,
) -> None:
    headers = doctor(api)
    plan_id = create_plan(api, headers).json()["id"]

    edited = api.client.patch(
        f"{PLANS}/{plan_id}",
        headers=headers,
        json={"content": {"items": [{**ITEM, "name": "Basal ajustada"}]}},
    )
    snapshots = api.client.get(f"{PLANS}/{plan_id}/snapshots", headers=headers)

    assert edited.status_code == 200, edited.text
    assert edited.json()["items"][0]["name"] == "Basal ajustada"
    assert snapshots.status_code == 200
    assert len(snapshots.json()["items"]) == 1


def test_an_active_plan_is_not_edited(api: IdentityApi) -> None:
    headers = doctor(api)
    plan_id = str(add_active_plan(api))

    response = api.client.patch(
        f"{PLANS}/{plan_id}", headers=headers, json={"content": CONTENT}
    )

    assert response.status_code == 409, response.text
    assert error_code(response) == "INVALID_STATE_TRANSITION"


def test_a_new_version_opens_a_draft_and_the_active_plan_stays(
    api: IdentityApi,
) -> None:
    headers = doctor(api)
    plan_id = str(add_active_plan(api))

    version = api.client.post(f"{PLANS}/{plan_id}/versions", headers=headers)

    assert version.status_code == 201, version.text
    assert version.json()["status"] == "DRAFT"
    assert version.json()["previous_plan_id"] == plan_id
    assert api.plans.rows[UUID(plan_id)].status is PlanStatus.ACTIVE


def test_a_restored_photo_becomes_a_new_draft(api: IdentityApi) -> None:
    headers = doctor(api)
    plan_id = create_plan(api, headers).json()["id"]
    api.client.patch(
        f"{PLANS}/{plan_id}",
        headers=headers,
        json={"content": {"items": [{**ITEM, "name": "Otra"}]}},
    )
    snapshot_id = api.client.get(
        f"{PLANS}/{plan_id}/snapshots", headers=headers
    ).json()["items"][0]["id"]

    restored = api.client.post(
        f"{PLANS}/{plan_id}/restore", headers=headers, json={"snapshot_id": snapshot_id}
    )

    assert restored.status_code == 201, restored.text
    assert restored.json()["status"] == "DRAFT"
    assert restored.json()["items"][0]["name"] == "Basal"


def test_the_doctor_lists_the_plans_of_an_assigned_patient(api: IdentityApi) -> None:
    headers = doctor(api)
    create_plan(api, headers)

    response = api.client.get(
        PLANS, headers=headers, params={"patient_id": str(PATIENT_ID)}
    )

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1
    assert response.json()["next_cursor"] is None


def test_the_plans_of_an_unassigned_patient_are_not_found(api: IdentityApi) -> None:
    response = api.client.get(
        PLANS, headers=doctor(api), params={"patient_id": str(OTHER_PATIENT)}
    )

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_plan_of_another_patient_has_the_same_404_as_a_missing_one(
    api: IdentityApi,
) -> None:
    headers = doctor(api)
    other = UUID(int=6002)
    api.plans.rows[other] = replace(
        draft(*plan_items(insulin())), plan_id=other, patient_id=OTHER_PATIENT
    )

    foreign = api.client.get(f"{PLANS}/{other}", headers=headers)
    missing = api.client.get(f"{PLANS}/{UUID(int=6999)}", headers=headers)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


# Templates: the clinic administrator.


def test_the_admin_creates_a_template_and_the_doctor_only_reads_it(
    api: IdentityApi,
) -> None:
    created = api.client.post(
        TEMPLATES,
        headers=admin(api),
        json={"name": "Basal-bolo adulto DM1", "content": CONTENT},
    )

    assert created.status_code == 201, created.text
    assert created.json()["code"] == "BASAL_BOLO_ADULTO_DM1"
    template_id = created.json()["id"]
    listed = api.client.get(TEMPLATES, headers=doctor(api))
    assert listed.status_code == 200
    assert template_id in {row["id"] for row in listed.json()["items"]}


def test_the_doctor_cannot_create_a_template(api: IdentityApi) -> None:
    response = api.client.post(
        TEMPLATES,
        headers=doctor(api),
        json={"name": "Nueva", "content": CONTENT},
    )

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_a_template_is_versioned_then_retired(api: IdentityApi) -> None:
    headers = admin(api)
    template_id = api.client.post(
        TEMPLATES, headers=headers, json={"name": "Protocolo", "content": CONTENT}
    ).json()["id"]

    version = api.client.post(
        f"{TEMPLATES}/{template_id}/versions",
        headers=headers,
        json={"content": CONTENT},
    )
    retired = api.client.post(f"{TEMPLATES}/{template_id}/retire", headers=headers)

    assert version.status_code == 201, version.text
    assert version.json()["version"] == 2
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "RETIRED"


def test_a_missing_template_is_not_found(api: IdentityApi) -> None:
    response = api.client.get(f"{TEMPLATES}/{UUID(int=7777)}", headers=doctor(api))

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


# The patient's own plan.


def test_the_patient_sees_the_active_plan_and_no_draft(api: IdentityApi) -> None:
    add_active_plan(api)
    api.plans.rows[UUID(int=6003)] = replace(
        draft(*plan_items(insulin("Borrador"))),
        plan_id=UUID(int=6003),
        patient_id=PATIENT_ID,
        clinic_id=CLINIC.clinic_id,
    )

    response = api.client.get(OWN_PLAN, headers=patient(api))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"
    assert "Borrador" not in response.text


def test_the_patient_without_an_active_plan_is_not_found(api: IdentityApi) -> None:
    response = api.client.get(OWN_PLAN, headers=patient(api))

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_doctor_cannot_read_the_own_plan_endpoint(api: IdentityApi) -> None:
    response = api.client.get(OWN_PLAN, headers=doctor(api))

    assert response.status_code == 403


def test_the_patient_cannot_manage_the_plans_of_others(api: IdentityApi) -> None:
    response = create_plan(api, patient(api))

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


# Contract: auth, validation and documentation.


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", TEMPLATES),
        ("post", PLANS),
        ("get", OWN_PLAN),
    ],
)
def test_the_treatment_endpoints_require_a_session(
    api: IdentityApi, method: str, path: str
) -> None:
    response = getattr(api.client, method)(path)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


def test_an_unknown_field_is_a_validation_error(api: IdentityApi) -> None:
    response = api.client.post(
        PLANS,
        headers=doctor(api),
        json={"patient_id": str(PATIENT_ID), "content": CONTENT, "extra": True},
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_an_insulin_dose_above_the_input_limit_is_refused(api: IdentityApi) -> None:
    item = {**ITEM, "dose_units": "5000"}

    response = create_plan(api, doctor(api), content={"items": [item]})

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_every_treatment_route_is_documented_in_spanish(api: IdentityApi) -> None:
    document = api.client.get("/openapi.json").json()
    operations = [
        operation
        for path, methods in document["paths"].items()
        if "treatment" in path or "protocol-templates" in path
        for operation in methods.values()
    ]

    assert len(operations) == 14
    for operation in operations:
        assert operation["operationId"]
        assert operation["summary"]
        assert operation["description"]
        assert operation["tags"] == ["Plan de tratamiento"]


def test_a_plan_has_no_ai_dose_suggestion_for_the_patient(api: IdentityApi) -> None:
    add_active_plan(api)

    response = api.client.get(OWN_PLAN, headers=patient(api))

    assert "recommendation" not in response.text
    assert "suggest" not in response.text


def test_the_injection_sites_of_an_item_are_stored_sorted_and_without_repeats(
    api: IdentityApi,
) -> None:
    item = {**ITEM, "injection_sites": ["THIGH_RIGHT", "ABDOMEN_LEFT", "THIGH_RIGHT"]}

    response = create_plan(api, doctor(api), content={"items": [item]})

    assert response.status_code == 201, response.text
    assert response.json()["items"][0]["injection_sites"] == [
        "ABDOMEN_LEFT",
        "THIGH_RIGHT",
    ]


def test_an_item_without_injection_sites_answers_null(api: IdentityApi) -> None:
    response = create_plan(api, doctor(api))

    assert response.json()["items"][0]["injection_sites"] is None


@pytest.mark.parametrize("sites", [[], ["CHEST_LEFT"]])
def test_an_empty_or_unknown_site_list_is_422(
    api: IdentityApi, sites: list[str]
) -> None:
    item = {**ITEM, "injection_sites": sites}

    response = create_plan(api, doctor(api), content={"items": [item]})

    assert response.status_code == 422, response.text


def test_the_patient_sees_the_sites_the_doctor_allows(api: IdentityApi) -> None:
    plan_id = UUID(int=6010)
    allowed = replace(insulin(), injection_sites=(SiteCode.BUTTOCK_LEFT,))
    api.plans.rows[plan_id] = active(
        replace(
            draft(*plan_items(allowed)),
            plan_id=plan_id,
            patient_id=PATIENT_ID,
            clinic_id=CLINIC.clinic_id,
        )
    )

    response = api.client.get(OWN_PLAN, headers=patient(api))

    assert response.json()["items"][0]["injection_sites"] == ["BUTTOCK_LEFT"]
