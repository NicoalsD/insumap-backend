"""Consent and privacy endpoints over the real app with port doubles (API.md 8.13)."""

from uuid import UUID

import pytest

from insumap.application.access.ports import DataAccessAction
from insumap.application.consents.ports import PrivacyNoticeView
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
ADMIN_USER = UUID(int=77)
PUBLIC_NOTICE = "/api/v1/public/privacy-notices"
OWN = "/api/v1/consents/own"
ACCEPT = f"{OWN}/acceptances"
WITHDRAW = f"{OWN}/withdrawals"
STATUSES = "/api/v1/consents"
REQUESTS = "/api/v1/privacy-requests"
PATIENT_PERMISSIONS = frozenset(
    {PermissionCode.CONSENTS_MANAGE_OWN, PermissionCode.PRIVACY_REQUESTS_CREATE_OWN}
)
ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.CONSENTS_READ_STATUS, PermissionCode.PRIVACY_REQUESTS_MANAGE}
)
NOTE = "Solicitud revisada por la clínica"


def error_code(response: object) -> str:
    return response.json()["error"]["code"]  # type: ignore[attr-defined,no-any-return]


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PATIENT_PERMISSIONS
    api.consents.notices.views[NOTICE_ID] = PrivacyNoticeView(
        version_id=NOTICE_ID,
        clinic_id=CLINIC.clinic_id,
        version="2026-11-01",
        content="Aviso de privacidad de la clínica demo.",
        effective_from=NOW,
    )
    return api


@pytest.fixture
def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


@pytest.fixture
def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN_USER, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def accept(api: IdentityApi, headers: dict[str, str]) -> None:
    response = api.client.post(
        ACCEPT,
        headers=headers,
        json={"privacy_notice_version_id": str(NOTICE_ID), "accepted": True},
    )
    assert response.status_code == 201, response.text


def create_request(api: IdentityApi, headers: dict[str, str]) -> dict[str, object]:
    response = api.client.post(
        REQUESTS, headers=headers, json={"request_type": "ACCESS"}
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


# The public notice.


def test_the_notice_is_readable_without_a_session(api: IdentityApi) -> None:
    response = api.client.get(f"{PUBLIC_NOTICE}/{NOTICE_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(NOTICE_ID)
    assert body["version"] == "2026-11-01"
    assert body["text"] == "Aviso de privacidad de la clínica demo."
    assert {s["scope"]: s["required"] for s in body["scopes"]} == {
        "SENSITIVE_DATA_PROCESSING": True,
        "AI_EXTERNAL_PROCESSING": False,
    }


def test_an_unknown_notice_is_not_found(api: IdentityApi) -> None:
    response = api.client.get(f"{PUBLIC_NOTICE}/{UUID(int=12345)}")

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


# Own consent: exempt from C3, so it works before the consent is given.


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", OWN),
        ("POST", ACCEPT),
        ("POST", WITHDRAW),
        ("GET", STATUSES),
        ("POST", REQUESTS),
        ("GET", REQUESTS),
        ("POST", f"{REQUESTS}/{UUID(int=1)}/resolve"),
        ("GET", f"{REQUESTS}/{UUID(int=1)}/export"),
    ],
)
def test_every_consent_route_needs_a_token(
    api: IdentityApi, method: str, path: str
) -> None:
    response = api.client.request(method, path)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


def test_a_patient_without_consent_can_still_read_and_accept_its_consent(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    before = api.client.get(OWN, headers=patient)
    accept(api, patient)
    after = api.client.get(OWN, headers=patient)

    assert before.status_code == 200
    assert before.json()["consent_required"] is True
    assert after.status_code == 200
    assert after.json()["consent_required"] is False
    assert after.json()["accepted_version_id"] == str(NOTICE_ID)


def test_accepting_an_outdated_version_is_a_conflict(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    response = api.client.post(
        ACCEPT,
        headers=patient,
        json={"privacy_notice_version_id": str(UUID(int=99)), "accepted": True},
    )

    assert response.status_code == 409
    assert error_code(response) == "CONSENT_VERSION_OUTDATED"


@pytest.mark.parametrize(
    "body",
    [
        {"privacy_notice_version_id": str(NOTICE_ID), "accepted": False},
        {"privacy_notice_version_id": str(NOTICE_ID), "accepted": True, "x": 1},
    ],
)
def test_an_acceptance_must_be_true_and_have_known_fields(
    api: IdentityApi, patient: dict[str, str], body: dict[str, object]
) -> None:
    response = api.client.post(ACCEPT, headers=patient, json=body)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_withdrawing_blocks_the_patient_until_it_accepts_again(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    accept(api, patient)

    withdrawn = api.client.post(
        WITHDRAW, headers=patient, json={"scope": "SENSITIVE_DATA_PROCESSING"}
    )
    again = api.client.post(
        WITHDRAW, headers=patient, json={"scope": "SENSITIVE_DATA_PROCESSING"}
    )

    assert withdrawn.status_code == 200
    assert withdrawn.json()["consent_required"] is True
    assert again.status_code == 409
    assert error_code(again) == "INVALID_STATE_TRANSITION"


def test_a_withdrawal_is_appended_and_never_deletes_the_acceptance(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    accept(api, patient)
    api.client.post(
        WITHDRAW, headers=patient, json={"scope": "SENSITIVE_DATA_PROCESSING"}
    )

    actions = [
        r.action for r in api.world.consents.records if r.patient_id == PATIENT_ID
    ]

    assert actions == [ConsentAction.ACCEPTED, ConsentAction.WITHDRAWN]


# Clinic statuses.


def test_a_patient_cannot_list_the_clinic_statuses(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    response = api.client.get(STATUSES, headers=patient)

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_the_administrator_lists_standing_and_the_list_is_audited(
    api: IdentityApi, patient: dict[str, str], admin: dict[str, str]
) -> None:
    accept(api, patient)

    response = api.client.get(STATUSES, headers=admin)

    assert response.status_code == 200
    items = response.json()["items"]
    assert items == [
        {
            "patient_id": str(PATIENT_ID),
            "standing": "GRANTED",
            "privacy_notice_version_id": str(NOTICE_ID),
            "occurred_at": items[0]["occurred_at"],
        }
    ]
    assert api.consents.access_log.granted[-1].resource.value == "PATIENT_LIST"


# Privacy requests.


def test_a_patient_without_consent_cannot_open_a_request(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    response = api.client.post(
        REQUESTS, headers=patient, json={"request_type": "ACCESS"}
    )

    assert response.status_code == 403
    assert error_code(response) == "CONSENT_REQUIRED"


def test_an_open_request_carries_its_status_and_deadline(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    accept(api, patient)

    created = create_request(api, patient)

    assert created["status"] == "OPEN"
    assert created["due_at"] is not None
    assert created["resolved_at"] is None


def test_the_request_body_is_strict(api: IdentityApi, patient: dict[str, str]) -> None:
    accept(api, patient)

    response = api.client.post(
        REQUESTS, headers=patient, json={"request_type": "NOPE", "extra": True}
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_the_clinic_resolves_a_request_and_a_second_decision_conflicts(
    api: IdentityApi,
    patient: dict[str, str],
    admin: dict[str, str],
) -> None:
    accept(api, patient)
    request_id = create_request(api, patient)["id"]
    body = {"decision": "APPROVE", "note": NOTE}

    resolved = api.client.post(
        f"{REQUESTS}/{request_id}/resolve", headers=admin, json=body
    )
    again = api.client.post(
        f"{REQUESTS}/{request_id}/resolve", headers=admin, json=body
    )

    assert resolved.status_code == 200
    assert resolved.json()["status"] == "APPROVED"
    assert again.status_code == 409
    assert error_code(again) == "INVALID_STATE_TRANSITION"


def test_the_patient_cannot_resolve_its_own_request(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    accept(api, patient)
    request_id = create_request(api, patient)["id"]

    response = api.client.post(
        f"{REQUESTS}/{request_id}/resolve",
        headers=patient,
        json={"decision": "APPROVE", "note": NOTE},
    )

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_resolving_an_unknown_request_is_not_found(
    api: IdentityApi, admin: dict[str, str]
) -> None:
    response = api.client.post(
        f"{REQUESTS}/{UUID(int=4242)}/resolve",
        headers=admin,
        json={"decision": "APPROVE", "note": NOTE},
    )

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_the_patient_lists_its_requests_and_the_clinic_lists_them_too(
    api: IdentityApi, patient: dict[str, str], admin: dict[str, str]
) -> None:
    accept(api, patient)
    request_id = create_request(api, patient)["id"]

    own = api.client.get(REQUESTS, headers=patient)
    clinic = api.client.get(REQUESTS, headers=admin)

    assert [item["id"] for item in own.json()["items"]] == [request_id]
    assert [item["id"] for item in clinic.json()["items"]] == [request_id]


def test_an_open_request_does_not_export(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    accept(api, patient)
    request_id = create_request(api, patient)["id"]

    response = api.client.get(f"{REQUESTS}/{request_id}/export", headers=patient)

    assert response.status_code == 409
    assert error_code(response) == "INVALID_STATE_TRANSITION"


def test_an_approved_request_exports_the_own_data_and_is_audited(
    api: IdentityApi, patient: dict[str, str], admin: dict[str, str]
) -> None:
    accept(api, patient)
    request_id = create_request(api, patient)["id"]
    api.client.post(
        f"{REQUESTS}/{request_id}/resolve",
        headers=admin,
        json={"decision": "APPROVE", "note": NOTE},
    )

    response = api.client.get(f"{REQUESTS}/{request_id}/export", headers=patient)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["request_id"] == request_id
    assert body["patient_id"] == str(PATIENT_ID)
    assert body["consents"][0]["scope"] == "SENSITIVE_DATA_PROCESSING"
    assert api.consents.access_log.granted[-1].action is DataAccessAction.EXPORT


def test_an_unknown_request_export_is_not_found(
    api: IdentityApi, patient: dict[str, str]
) -> None:
    accept(api, patient)
    response = api.client.get(f"{REQUESTS}/{UUID(int=4343)}/export", headers=patient)

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_a_seeded_acceptance_is_visible_to_the_patient(
    api: IdentityApi, patient: dict[str, str]
) -> None:
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

    body = api.client.get(OWN, headers=patient).json()

    assert body["consent_required"] is False
