"""Staff endpoints (API.md 8.3, ``/api/v1/users``) over the real app and doubles."""

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import (
    DOCTOR_USER,
    ENROLLING_DOCTOR,
    PATIENT_USER,
    STAFF_INVITED_USER,
    make_account,
)

BASE = "/api/v1/users"
ADMIN = UUID(int=900)
OTHER_CLINIC_STAFF = UUID(int=950)
MISSING = UUID(int=999)
REASON = "Salida de la clínica del personal"
ADMIN_PERMISSIONS = frozenset({PermissionCode.USERS_MANAGE, PermissionCode.USERS_READ})
CODE = "ABCD-EFGH-JKMN-PQRS"


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    return api


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def new_doctor(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "email": "nueva.medica@example.test",
        "full_name": "Nueva Médica de Prueba",
        "role": "DOCTOR",
        "professional_license": "RM-1001",
        "specialty": "Endocrinología",
    }
    body.update(overrides)
    return body


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def test_creating_a_doctor_answers_201_and_emails_the_code(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(BASE, headers=headers, json=new_doctor())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "nueva.medica@example.test"
    assert body["role"] == "DOCTOR"
    assert body["is_active"] is False
    assert body["invitation_expires_at"]
    assert response.headers["Location"] == f"{BASE}/{body['id']}"
    [delivered] = api.mail.delivered
    assert CODE in delivered.body
    assert CODE not in response.text
    assert "USER_CREATED" in [entry.action for entry in api.audit_log.entries]


def test_a_taken_email_is_a_conflict_and_sends_nothing(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(
        BASE, headers=headers, json=new_doctor(email="medico@example.test")
    )

    assert response.status_code == 409
    assert error_code(response) == "CONFLICT"
    assert api.mail.delivered == []


def test_a_doctor_without_license_is_422(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(
        BASE, headers=headers, json=new_doctor(professional_license=None)
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "overrides",
    [
        {"unknown": 1},
        {"role": "PATIENT"},
        {"full_name": "   "},
        {"email": "no-es-un-correo"},
    ],
)
def test_invalid_bodies_are_422_and_create_nothing(
    api: IdentityApi, overrides: dict[str, Any]
) -> None:
    headers = admin(api)

    response = api.client.post(BASE, headers=headers, json=new_doctor(**overrides))

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert api.mail.delivered == []


def test_listing_returns_the_clinic_staff_filtered_by_role(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.get(BASE, headers=headers, params={"role": "DOCTOR"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["id"] for item in body["items"]} == {
        str(DOCTOR_USER),
        str(ENROLLING_DOCTOR),
        str(STAFF_INVITED_USER),
    }
    assert body["next_cursor"] is None
    assert "clinical" not in response.text


def test_listing_is_paginated(api: IdentityApi) -> None:
    headers = admin(api)

    first = api.client.get(BASE, headers=headers, params={"limit": 1})
    second = api.client.get(
        BASE,
        headers=headers,
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )

    assert first.status_code == 200
    assert len(first.json()["items"]) == 1
    assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]


def test_get_shows_the_profile_and_the_mfa_state(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.get(f"{BASE}/{DOCTOR_USER}", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(DOCTOR_USER)
    assert body["mfa_enabled"] is True
    assert body["professional_license"] is None


def test_patch_changes_only_the_fields_that_were_sent(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.patch(
        f"{BASE}/{DOCTOR_USER}", headers=headers, json={"specialty": "Endocrinología"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["specialty"] == "Endocrinología"
    assert body["full_name"] == "Persona de Prueba"
    assert "USER_UPDATED" in [entry.action for entry in api.audit_log.entries]


@pytest.mark.parametrize(
    "payload",
    [{"full_name": None}, {"specialty": "   "}, {"unknown": "x"}],
)
def test_patch_refuses_null_names_blank_text_and_unknown_fields(
    api: IdentityApi, payload: dict[str, Any]
) -> None:
    headers = admin(api)

    response = api.client.patch(f"{BASE}/{DOCTOR_USER}", headers=headers, json=payload)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_deactivation_closes_the_account_and_a_second_one_is_a_conflict(
    api: IdentityApi,
) -> None:
    headers = admin(api)
    url = f"{BASE}/{ENROLLING_DOCTOR}/deactivate"

    first = api.client.post(url, headers=headers, json={"reason": REASON})
    second = api.client.post(url, headers=headers, json={"reason": REASON})

    assert first.status_code == 200, first.text
    assert first.json()["is_active"] is False
    assert first.json()["patients_pending_reassignment"] == 0
    assert second.status_code == 409
    assert error_code(second) == "INVALID_STATE_TRANSITION"


def test_deactivation_needs_a_reason(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(
        f"{BASE}/{ENROLLING_DOCTOR}/deactivate", headers=headers, json={}
    )

    assert response.status_code == 422


def test_unlock_answers_204_and_clears_the_account_lock(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(f"{BASE}/{DOCTOR_USER}/unlock", headers=headers)

    assert response.status_code == 204, response.text
    assert api.login_lockouts.cleared == ["medico@example.test"]


def test_mfa_reset_removes_the_factor_and_answers_204(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(
        f"{BASE}/{DOCTOR_USER}/mfa-reset", headers=headers, json={"reason": REASON}
    )

    assert response.status_code == 204, response.text
    after = api.client.get(f"{BASE}/{DOCTOR_USER}", headers=headers)
    assert after.json()["mfa_enabled"] is False


def test_nobody_resets_their_own_mfa(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(
        f"{BASE}/{ADMIN}/mfa-reset", headers=headers, json={"reason": REASON}
    )

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_mfa_reset_needs_a_reason_of_the_allowed_length(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.post(
        f"{BASE}/{DOCTOR_USER}/mfa-reset", headers=headers, json={"reason": "corto"}
    )

    assert response.status_code == 422


def other_clinic_user(api: IdentityApi) -> None:
    """A doctor of another clinic, added to the same in-memory accounts."""
    outside = make_account(OTHER_CLINIC_STAFF, "fuera@example.test", role=Role.DOCTOR)
    api.world.users.add(
        replace(
            outside,
            clinic=ClinicSummary(
                clinic_id=UUID(int=11),
                name="Otra Clínica",
                is_demo=True,
                is_active=True,
            ),
        )
    )


@pytest.mark.parametrize("path", ["", "/unlock", "/deactivate", "/mfa-reset"])
def test_other_clinics_patients_and_missing_users_get_the_same_404(
    api: IdentityApi, path: str
) -> None:
    other_clinic_user(api)
    headers = admin(api)
    bodies = []
    for user_id in (OTHER_CLINIC_STAFF, PATIENT_USER, MISSING):
        url = f"{BASE}/{user_id}{path}"
        if path == "":
            response = api.client.get(url, headers=headers)
        elif path == "/unlock":
            response = api.client.post(url, headers=headers)
        else:
            response = api.client.post(url, headers=headers, json={"reason": REASON})
        assert response.status_code == 404, response.text
        bodies.append(response.json())

    assert bodies[0] == bodies[1] == bodies[2]


def test_a_patient_is_not_staff_even_in_the_same_clinic(api: IdentityApi) -> None:
    headers = admin(api)

    response = api.client.get(f"{BASE}/{PATIENT_USER}", headers=headers)

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"


def test_without_token_every_route_is_401(api: IdentityApi) -> None:
    responses = [
        api.client.get(BASE),
        api.client.post(BASE, json=new_doctor()),
        api.client.get(f"{BASE}/{DOCTOR_USER}"),
        api.client.patch(f"{BASE}/{DOCTOR_USER}", json={}),
        api.client.post(f"{BASE}/{DOCTOR_USER}/deactivate", json={"reason": REASON}),
        api.client.post(f"{BASE}/{DOCTOR_USER}/unlock"),
        api.client.post(f"{BASE}/{DOCTOR_USER}/mfa-reset", json={"reason": REASON}),
    ]

    assert [response.status_code for response in responses] == [401] * 7


def test_without_the_permission_every_route_is_403(api: IdentityApi) -> None:
    token = api.staff_token(OTHER_CLINIC_STAFF, Role.DOCTOR, frozenset())
    headers = api.bearer(token)

    responses = [
        api.client.get(BASE, headers=headers),
        api.client.post(BASE, headers=headers, json=new_doctor()),
        api.client.get(f"{BASE}/{DOCTOR_USER}", headers=headers),
        api.client.patch(f"{BASE}/{DOCTOR_USER}", headers=headers, json={}),
        api.client.post(
            f"{BASE}/{DOCTOR_USER}/deactivate", headers=headers, json={"reason": REASON}
        ),
        api.client.post(f"{BASE}/{DOCTOR_USER}/unlock", headers=headers),
        api.client.post(
            f"{BASE}/{DOCTOR_USER}/mfa-reset", headers=headers, json={"reason": REASON}
        ),
    ]

    assert [response.status_code for response in responses] == [403] * 7
