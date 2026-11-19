"""Recommendation endpoints over the real app with doubles (API.md 8.10)."""

from typing import Any
from uuid import UUID

import pytest

from insumap.domain.ai.recommendation_state import RecommendationStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import PATIENT_ID
from tests.support.recommendation_fakes import make_recommendation

DOCTOR = UUID(int=910)
OTHER_PATIENT = UUID(int=911)
BASE = "/api/v1/recommendations"
RECOMMENDATION = UUID(int=920)
UNKNOWN = UUID(int=921)
REASON = "El ayuno fue producto de una cena tardía."
DECIDE = frozenset(
    {
        PermissionCode.RECOMMENDATIONS_DECIDE,
        PermissionCode.RECOMMENDATIONS_READ_ASSIGNED,
    }
)
READ_ONLY = frozenset({PermissionCode.RECOMMENDATIONS_READ_ASSIGNED})
MODIFY_BODY: dict[str, Any] = {
    "modified_proposal": {
        "action": "INCREASE",
        "current_dose_units": 24.0,
        "proposed_dose_units": 25.0,
        "delta_units": 1.0,
    },
    "reason": REASON,
}


@pytest.fixture
def api() -> IdentityApi:
    harness = IdentityApi()
    harness.records.patients.assigned.add((DOCTOR, PATIENT_ID))
    harness.recommendations.assignments.add((DOCTOR, PATIENT_ID))
    harness.recommendations.items[RECOMMENDATION] = make_recommendation(
        recommendation_id=RECOMMENDATION, patient_id=PATIENT_ID
    )
    harness.recommendations.items[UUID(int=930)] = make_recommendation(
        recommendation_id=UUID(int=930), patient_id=OTHER_PATIENT
    )
    return harness


def doctor_headers(
    api: IdentityApi, permissions: frozenset[PermissionCode] = DECIDE
) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, permissions))


def test_the_doctor_lists_and_reads_an_assigned_recommendation(
    api: IdentityApi,
) -> None:
    headers = doctor_headers(api, READ_ONLY)

    listing = api.client.get(BASE, headers=headers)
    detail = api.client.get(f"{BASE}/{RECOMMENDATION}", headers=headers)

    assert listing.status_code == 200
    items = listing.json()["items"]
    assert [item["id"] for item in items] == [str(RECOMMENDATION)]
    assert items[0]["proposal"]["requires_doctor_approval"] is True
    assert detail.status_code == 200
    assert detail.json()["decisions"] == []


def test_the_list_never_shows_a_patient_not_assigned(api: IdentityApi) -> None:
    response = api.client.get(BASE, headers=doctor_headers(api, READ_ONLY))

    assert str(UUID(int=930)) not in [item["id"] for item in response.json()["items"]]


def test_approve_records_the_decision_and_opens_a_draft(api: IdentityApi) -> None:
    headers = doctor_headers(api)

    response = api.client.post(f"{BASE}/{RECOMMENDATION}/approve", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == RecommendationStatus.APPROVED.value
    assert body["draft_plan_id"] is not None


def test_modify_keeps_the_change_and_its_reason(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/{RECOMMENDATION}/modify",
        headers=doctor_headers(api),
        json=MODIFY_BODY,
    )

    assert response.status_code == 200
    assert response.json()["status"] == RecommendationStatus.APPROVED_WITH_CHANGES.value
    detail = api.client.get(
        f"{BASE}/{RECOMMENDATION}", headers=doctor_headers(api, READ_ONLY)
    ).json()
    (decision,) = detail["decisions"]
    assert decision["reason"] == REASON
    assert decision["modified_suggestion"]["proposed_dose_units"] == 25.0


def test_reject_needs_a_reason(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/{RECOMMENDATION}/reject",
        headers=doctor_headers(api),
        json={"reason": "corto"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_reject_with_a_reason_is_recorded(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/{RECOMMENDATION}/reject",
        headers=doctor_headers(api),
        json={"reason": REASON},
    )

    assert response.status_code == 200
    assert response.json()["status"] == RecommendationStatus.REJECTED.value


def test_a_decided_recommendation_answers_409(api: IdentityApi) -> None:
    headers = doctor_headers(api)
    api.client.post(f"{BASE}/{RECOMMENDATION}/approve", headers=headers)

    response = api.client.post(
        f"{BASE}/{RECOMMENDATION}/reject",
        headers=headers,
        json={"reason": REASON},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_without_a_token_the_answer_is_401(api: IdentityApi) -> None:
    assert api.client.get(BASE).status_code == 401
    assert api.client.post(f"{BASE}/{RECOMMENDATION}/approve").status_code == 401


def test_without_the_decision_permission_the_answer_is_403(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/{RECOMMENDATION}/approve", headers=doctor_headers(api, READ_ONLY)
    )

    assert response.status_code == 403


def test_an_unassigned_patient_answers_like_a_missing_one(api: IdentityApi) -> None:
    headers = doctor_headers(api, READ_ONLY)

    not_assigned = api.client.get(f"{BASE}/{UUID(int=930)}", headers=headers)
    missing = api.client.get(f"{BASE}/{UNKNOWN}", headers=headers)

    assert not_assigned.status_code == missing.status_code == 404
    assert not_assigned.json() == missing.json()


def test_an_unknown_field_is_a_validation_error(api: IdentityApi) -> None:
    response = api.client.post(
        f"{BASE}/{RECOMMENDATION}/modify",
        headers=doctor_headers(api),
        json={**MODIFY_BODY, "dose": 99},
    )

    assert response.status_code == 422


def test_a_dose_above_the_technical_limit_is_refused(api: IdentityApi) -> None:
    body = {
        **MODIFY_BODY,
        "modified_proposal": {
            **MODIFY_BODY["modified_proposal"],
            "proposed_dose_units": 9999,
        },
    }

    response = api.client.post(
        f"{BASE}/{RECOMMENDATION}/modify", headers=doctor_headers(api), json=body
    )

    assert response.status_code == 422


def test_no_recommendation_response_holds_a_patient_name_or_a_document(
    api: IdentityApi,
) -> None:
    text = api.client.get(BASE, headers=doctor_headers(api, READ_ONLY)).text

    assert "email" not in text
    assert "document" not in text
