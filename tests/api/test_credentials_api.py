"""Patient credential endpoints over the real app with port doubles (API.md 8.4)."""

import re
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from insumap.application.credentials.ports import PatientContact
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import make_account

ADMIN = UUID(int=900)
DOCTOR = UUID(int=901)
CLINIC_ID = UUID(int=10)
OTHER_CLINIC_ID = UUID(int=20)
IMPORTED_PATIENT = UUID(int=700)
IMPORTED_USER = UUID(int=701)
SECOND_PATIENT = UUID(int=702)
SECOND_USER = UUID(int=703)
ACTIVE_PATIENT = UUID(int=704)
ACTIVE_USER = UUID(int=705)
OUTSIDE_PATIENT = UUID(int=706)
OUTSIDE_USER = UUID(int=707)
MISSING = UUID(int=999)
CONTACT_EMAIL = "paciente.importado@example.test"
ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.CREDENTIALS_ISSUE, PermissionCode.CREDENTIALS_REVOKE}
)
CODE_PATTERN = re.compile(r"^[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}-[0-9A-Z]{4}$")
ISSUE = "/api/v1/patients/{patient_id}/credential-invitations"
BATCH = "/api/v1/credential-invitations/batch"
REVOKE = "/api/v1/credential-invitations/{invitation_id}/revoke"


def add_patient(
    api: IdentityApi,
    *,
    patient_id: UUID,
    user_id: UUID,
    status: AccountStatus = AccountStatus.IMPORTED,
    clinic_id: UUID = CLINIC_ID,
    email: str | None = CONTACT_EMAIL,
) -> None:
    account = make_account(
        user_id,
        None if status is AccountStatus.IMPORTED else email,
        status=status,
        password=None if status is AccountStatus.IMPORTED else "x",
        patient_id=patient_id,
    )
    if clinic_id != CLINIC_ID:
        account = replace(
            account,
            clinic=ClinicSummary(
                clinic_id=clinic_id, name="Otra", is_demo=True, is_active=True
            ),
        )
    api.world.users.add(account)
    api.credential_contacts.add(
        PatientContact(
            patient_id=patient_id,
            clinic_id=clinic_id,
            user_id=user_id,
            contact_email=email,
        )
    )


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    add_patient(api, patient_id=IMPORTED_PATIENT, user_id=IMPORTED_USER)
    add_patient(api, patient_id=SECOND_PATIENT, user_id=SECOND_USER)
    add_patient(
        api, patient_id=ACTIVE_PATIENT, user_id=ACTIVE_USER, status=AccountStatus.ACTIVE
    )
    add_patient(
        api,
        patient_id=OUTSIDE_PATIENT,
        user_id=OUTSIDE_USER,
        clinic_id=OTHER_CLINIC_ID,
    )
    return api


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def doctor(api: IdentityApi) -> dict[str, str]:
    """A doctor holds no credential permission: every credential route is a 403."""
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, frozenset()))


def issue(
    api: IdentityApi,
    headers: dict[str, str],
    patient: UUID,
    channel: str = "PRINT",
) -> Any:
    return api.client.post(
        ISSUE.format(patient_id=patient), headers=headers, json={"channel": channel}
    )


def test_print_shows_the_code_once_with_no_store(api: IdentityApi) -> None:
    response = issue(api, admin(api), IMPORTED_PATIENT)

    assert response.status_code == 201, response.text
    body = response.json()
    assert CODE_PATTERN.match(body["activation_code"])
    assert body["purpose"] == "PATIENT_ACTIVATION"
    assert body["status"] == "PENDING"
    assert body["channel"] == "PRINT"
    assert body["delivery_status"] == "NOT_APPLICABLE"
    assert datetime.fromisoformat(body["expires_at"]).tzinfo is not None
    assert response.headers["cache-control"] == "no-store"
    assert api.mail.delivered == []


def test_the_code_is_never_written_to_the_audit_log(api: IdentityApi) -> None:
    code = issue(api, admin(api), IMPORTED_PATIENT).json()["activation_code"]

    (entry,) = api.audit_log.entries
    assert entry.action == "CREDENTIALS_ISSUED"
    assert entry.entity_type == "CREDENTIAL_INVITATION"
    assert code.replace("-", "") not in repr(entry)


def test_email_sends_the_link_and_hides_the_code(api: IdentityApi) -> None:
    response = issue(api, admin(api), IMPORTED_PATIENT, channel="EMAIL")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["activation_code"] is None
    assert body["delivery_status"] == "PENDING"
    (sent,) = api.mail.delivered
    assert sent.recipient.address == CONTACT_EMAIL
    assert "#code=" in sent.body


def test_reissue_revokes_the_previous_invitation(api: IdentityApi) -> None:
    headers = admin(api)
    first = issue(api, headers, IMPORTED_PATIENT).json()
    second = issue(api, headers, IMPORTED_PATIENT).json()

    assert first["invitation_id"] != second["invitation_id"]
    assert first["activation_code"] != second["activation_code"]
    old = api.credential_invitations.row(UUID(first["invitation_id"]))
    assert old.invitation.status.value == "REVOKED"
    assert str(old.replaced_by_id) == second["invitation_id"]


def test_a_patient_past_activation_is_a_state_conflict(api: IdentityApi) -> None:
    response = issue(api, admin(api), ACTIVE_PATIENT)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert api.credential_invitations.rows == {}


def test_unknown_and_other_clinic_patients_share_one_body(api: IdentityApi) -> None:
    headers = admin(api)

    missing = issue(api, headers, MISSING)
    other = issue(api, headers, OUTSIDE_PATIENT)

    assert missing.status_code == other.status_code == 404
    assert missing.json() == other.json()
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_email_without_a_contact_address_is_a_field_error(api: IdentityApi) -> None:
    add_patient(api, patient_id=UUID(int=708), user_id=UUID(int=709), email=None)

    response = issue(api, admin(api), UUID(int=708), channel="EMAIL")

    assert response.status_code == 422
    assert response.json()["error"]["detail"] == {
        "errors": [{"field": "body.channel", "type": "missing_contact_email"}]
    }


def test_unknown_channel_and_unknown_field_are_422(api: IdentityApi) -> None:
    headers = admin(api)

    bad_channel = issue(api, headers, IMPORTED_PATIENT, channel="SMS")
    extra = api.client.post(
        ISSUE.format(patient_id=IMPORTED_PATIENT),
        headers=headers,
        json={"channel": "PRINT", "patient_name": "x"},
    )

    assert bad_channel.status_code == 422
    assert extra.status_code == 422
    assert extra.json()["error"]["code"] == "VALIDATION_ERROR"


def test_without_a_token_it_is_401(api: IdentityApi) -> None:
    response = api.client.post(
        ISSUE.format(patient_id=IMPORTED_PATIENT), json={"channel": "PRINT"}
    )

    assert response.status_code == 401


def test_without_the_permission_it_is_403(api: IdentityApi) -> None:
    response = issue(api, doctor(api), IMPORTED_PATIENT)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_the_clinic_limit_answers_429_and_issues_nothing(api: IdentityApi) -> None:
    headers = admin(api)
    api.world.limiter.blocked = True

    response = issue(api, headers, IMPORTED_PATIENT)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert api.credential_invitations.rows == {}


def test_batch_reports_each_patient_with_its_own_outcome(api: IdentityApi) -> None:
    response = api.client.post(
        BATCH,
        headers=admin(api),
        json={
            "patient_ids": [
                str(IMPORTED_PATIENT),
                str(ACTIVE_PATIENT),
                str(MISSING),
                str(SECOND_PATIENT),
            ],
            "channel": "PRINT",
        },
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["patient_id"] for item in items] == [
        str(IMPORTED_PATIENT),
        str(ACTIVE_PATIENT),
        str(MISSING),
        str(SECOND_PATIENT),
    ]
    assert items[0]["status"] == "ISSUED"
    assert CODE_PATTERN.match(items[0]["activation_code"])
    assert items[1]["status"] == "FAILED"
    assert items[1]["error_code"] == "INVALID_STATE_TRANSITION"
    assert items[2]["error_code"] == "NOT_FOUND"
    assert items[3]["status"] == "ISSUED"
    assert response.headers["cache-control"] == "no-store"


def test_batch_by_email_returns_no_codes(api: IdentityApi) -> None:
    response = api.client.post(
        BATCH,
        headers=admin(api),
        json={"patient_ids": [str(IMPORTED_PATIENT)], "channel": "EMAIL"},
    )

    assert response.status_code == 200, response.text
    (item,) = response.json()["items"]
    assert item["status"] == "ISSUED"
    assert item["activation_code"] is None
    assert len(api.mail.delivered) == 1


@pytest.mark.parametrize(
    "ids",
    [
        [],
        [str(IMPORTED_PATIENT), str(IMPORTED_PATIENT)],
        [str(UUID(int=5000 + index)) for index in range(101)],
    ],
    ids=["empty", "repeated", "over-the-limit"],
)
def test_batch_rejects_bad_lists_with_422(api: IdentityApi, ids: list[str]) -> None:
    response = api.client.post(
        BATCH, headers=admin(api), json={"patient_ids": ids, "channel": "PRINT"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.credential_invitations.rows == {}


def test_batch_without_the_permission_is_403(api: IdentityApi) -> None:
    response = api.client.post(
        BATCH,
        headers=doctor(api),
        json={"patient_ids": [str(IMPORTED_PATIENT)], "channel": "PRINT"},
    )

    assert response.status_code == 403


def test_batch_refused_by_its_limit_issues_nothing(api: IdentityApi) -> None:
    headers = admin(api)
    api.world.limiter.blocked = True

    response = api.client.post(
        BATCH,
        headers=headers,
        json={"patient_ids": [str(IMPORTED_PATIENT)], "channel": "PRINT"},
    )

    assert response.status_code == 429
    assert api.credential_invitations.rows == {}


def test_revoke_returns_the_patient_to_imported(api: IdentityApi) -> None:
    headers = admin(api)
    issued = issue(api, headers, IMPORTED_PATIENT).json()

    response = api.client.post(
        REVOKE.format(invitation_id=issued["invitation_id"]), headers=headers
    )

    assert response.status_code == 204, response.text
    assert response.content == b""
    account = api.world.users.get(IMPORTED_USER)
    assert account is not None
    assert account.status is AccountStatus.IMPORTED
    assert [e.action for e in api.audit_log.entries][-1] == (
        "CREDENTIAL_INVITATION_REVOKED"
    )


def test_revoking_twice_is_a_state_conflict(api: IdentityApi) -> None:
    headers = admin(api)
    issued = issue(api, headers, IMPORTED_PATIENT).json()
    path = REVOKE.format(invitation_id=issued["invitation_id"])
    api.client.post(path, headers=headers)

    response = api.client.post(path, headers=headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_revoking_an_unknown_invitation_is_404(api: IdentityApi) -> None:
    response = api.client.post(
        REVOKE.format(invitation_id=str(UUID(int=12345))), headers=admin(api)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_revoke_without_the_permission_is_403(api: IdentityApi) -> None:
    headers = admin(api)
    issued = issue(api, headers, IMPORTED_PATIENT).json()

    response = api.client.post(
        REVOKE.format(invitation_id=issued["invitation_id"]), headers=doctor(api)
    )

    assert response.status_code == 403


def test_the_routes_are_in_swagger_with_their_permission(api: IdentityApi) -> None:
    schema = api.client.get("/openapi.json").json()

    issue_op = schema["paths"][ISSUE]["post"]
    assert (
        issue_op["summary"]
        == "Emitir o reemitir el código de activación de un paciente"
    )
    assert issue_op["x-access"] == "permission:credentials.issue"
    assert schema["paths"][BATCH]["post"]["x-access"] == "permission:credentials.issue"
    assert (
        schema["paths"][REVOKE]["post"]["x-access"] == "permission:credentials.revoke"
    )
