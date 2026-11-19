"""Patient administration and own profile over the real app (API.md 8.4 and 8.6)."""

from typing import Any
from uuid import UUID

import pytest

from insumap.application.access.ports import DataResource
from insumap.application.patients.ports import PatientAdministrativeView
from insumap.domain.access.policy import PatientRef
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.invitation import InvitationStatus
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
from tests.support.monitoring_fakes import TEST_PROFILE

ADMIN = UUID(int=800)
DOCTOR = UUID(int=801)
OTHER_PATIENT = UUID(int=777)
OTHER_PATIENT_USER = UUID(int=778)
OTHER_CLINIC = UUID(int=77)
MISSING_PATIENT = UUID(int=404)
PATIENT_EMAIL = "paciente@example.test"
REASON = "Suspensión por revisión administrativa"
ROSTER = "/api/v1/patients"
OWN = "/api/v1/patients/own"
ADMIN_PERMISSIONS = frozenset(
    {PermissionCode.PATIENTS_READ_ROSTER, PermissionCode.PATIENTS_MANAGE_STATUS}
)
DOCTOR_PERMISSIONS = frozenset({PermissionCode.CARE_TEAM_READ})
ROSTER_KEYS = {
    "id",
    "full_name",
    "mrn",
    "document_last4",
    "account_status",
    "primary_doctor_id",
    "assigned_doctor_count",
    "invitation_status",
    "simulated",
}
OWN_KEYS = {"id", "account_status", "clinic", "target_profile", "simulated"}


def admin_view(
    patient_id: UUID = PATIENT_ID,
    *,
    clinic_id: UUID = CLINIC.clinic_id,
    status: AccountStatus = AccountStatus.ACTIVE,
) -> PatientAdministrativeView:
    return PatientAdministrativeView(
        patient_id=patient_id,
        clinic_id=clinic_id,
        full_name="Pedro Paciente Demo",
        mrn="DEMO-0001",
        document_last4="1234",
        account_status=status,
        primary_doctor_id=DOCTOR,
        assigned_doctor_count=1,
        invitation_status=InvitationStatus.USED,
        simulated=True,
    )


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = frozenset(
        {PermissionCode.PATIENTS_READ_OWN}
    )
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=921),
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
    api.patients.patients[PATIENT_ID] = PatientRef(
        patient_id=PATIENT_ID, clinic_id=CLINIC.clinic_id, user_id=PATIENT_USER
    )
    api.patients.patients[OTHER_PATIENT] = PatientRef(
        patient_id=OTHER_PATIENT, clinic_id=OTHER_CLINIC, user_id=OTHER_PATIENT_USER
    )
    api.patient_roster.views[PATIENT_ID] = admin_view()
    api.patient_roster.views[OTHER_PATIENT] = admin_view(
        OTHER_PATIENT, clinic_id=OTHER_CLINIC
    )
    return api


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return api.bearer(login.json()["access_token"])


def error_code(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


def status_url(patient_id: UUID, action: str) -> str:
    return f"{ROSTER}/{patient_id}/{action}"


# --- GET /patients -----------------------------------------------------------


def test_admin_lists_the_clinic_patients_with_administrative_fields_only(
    api: IdentityApi,
) -> None:
    response = api.client.get(ROSTER, headers=admin(api))

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(PATIENT_ID)]
    assert set(body["items"][0]) == ROSTER_KEYS
    assert body["items"][0]["document_last4"] == "1234"
    assert "document_ciphertext" not in response.text
    assert "document_hash" not in response.text
    assert body["next_cursor"] is None
    logged = api.patient_log.granted[-1]
    assert logged.resource is DataResource.PATIENT_LIST
    assert logged.patient_id is None


def test_roster_filters_narrow_the_listing(api: IdentityApi) -> None:
    headers = admin(api)

    active = api.client.get(
        ROSTER, headers=headers, params={"account_status": "ACTIVE"}
    )
    suspended = api.client.get(
        ROSTER, headers=headers, params={"account_status": "SUSPENDED"}
    )
    unassigned = api.client.get(
        ROSTER, headers=headers, params={"without_doctor": "true"}
    )

    assert [item["id"] for item in active.json()["items"]] == [str(PATIENT_ID)]
    assert suspended.json()["items"] == []
    assert unassigned.json()["items"] == []


def test_invalid_roster_query_is_a_422(api: IdentityApi) -> None:
    headers = admin(api)

    unknown_status = api.client.get(
        ROSTER, headers=headers, params={"account_status": "EN_PAUSA"}
    )
    zero_limit = api.client.get(ROSTER, headers=headers, params={"limit": 0})
    bad_cursor = api.client.get(ROSTER, headers=headers, params={"cursor": "!!"})

    assert unknown_status.status_code == 422, unknown_status.text
    assert zero_limit.status_code == 422
    assert bad_cursor.status_code == 422
    assert error_code(unknown_status) == "VALIDATION_ERROR"


def test_roster_without_token_is_401(api: IdentityApi) -> None:
    response = api.client.get(ROSTER)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


def test_doctor_without_the_roster_permission_is_403(api: IdentityApi) -> None:
    response = api.client.get(ROSTER, headers=doctor(api))

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_patient_cannot_read_the_roster(api: IdentityApi) -> None:
    response = api.client.get(ROSTER, headers=patient(api))

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


# --- GET /patients/{patient_id} ----------------------------------------------


def test_admin_reads_one_patient_and_the_read_is_audited(api: IdentityApi) -> None:
    response = api.client.get(f"{ROSTER}/{PATIENT_ID}", headers=admin(api))

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(PATIENT_ID)
    assert set(response.json()) == ROSTER_KEYS
    logged = api.patient_log.granted[-1]
    assert logged.resource is DataResource.PATIENT_DEMOGRAPHICS
    assert logged.patient_id == PATIENT_ID


def test_other_clinic_and_missing_patient_answer_the_same_404(
    api: IdentityApi,
) -> None:
    headers = admin(api)

    other = api.client.get(f"{ROSTER}/{OTHER_PATIENT}", headers=headers)
    missing = api.client.get(f"{ROSTER}/{MISSING_PATIENT}", headers=headers)

    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    assert error_code(other) == "NOT_FOUND"
    assert len(api.patient_log.denied) == 2
    assert all(
        row.resource is DataResource.PATIENT_DEMOGRAPHICS
        for row in api.patient_log.denied
    )


def test_doctor_is_403_before_the_lookup_even_for_a_missing_id(
    api: IdentityApi,
) -> None:
    response = api.client.get(f"{ROSTER}/{MISSING_PATIENT}", headers=doctor(api))

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_detail_with_a_malformed_id_is_a_422(api: IdentityApi) -> None:
    response = api.client.get(f"{ROSTER}/no-es-un-id", headers=admin(api))

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_detail_without_token_is_401(api: IdentityApi) -> None:
    response = api.client.get(f"{ROSTER}/{PATIENT_ID}")

    assert response.status_code == 401


# --- POST /patients/{patient_id}/suspend, reactivate, deactivate -------------


def test_suspend_moves_the_account_and_ends_the_patient_session(
    api: IdentityApi,
) -> None:
    patient_headers = patient(api)

    response = api.client.post(
        status_url(PATIENT_ID, "suspend"),
        headers=admin(api),
        json={"reason": REASON},
    )

    assert response.status_code == 200, response.text
    assert response.json()["account_status"] == "SUSPENDED"
    account = api.world.users.accounts[PATIENT_USER]
    assert account.status is AccountStatus.SUSPENDED
    assert account.token_version == 1
    own = api.client.get(OWN, headers=patient_headers)
    assert own.status_code == 401
    assert error_code(own) == "SESSION_REVOKED"
    assert any(e.action == "PATIENT_SUSPENDED" for e in api.audit_log.entries)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"reason": "corta"},
        {"reason": REASON, "extra": 1},
    ],
)
def test_suspend_rejects_a_missing_short_or_unknown_field_with_422(
    api: IdentityApi, body: dict[str, Any]
) -> None:
    response = api.client.post(
        status_url(PATIENT_ID, "suspend"), headers=admin(api), json=body
    )

    assert response.status_code == 422, response.text
    assert error_code(response) == "VALIDATION_ERROR"


def test_suspend_of_an_account_that_is_not_active_is_409(api: IdentityApi) -> None:
    headers = admin(api)
    api.client.post(
        status_url(PATIENT_ID, "deactivate"), headers=headers, json={"reason": REASON}
    )

    response = api.client.post(
        status_url(PATIENT_ID, "suspend"), headers=headers, json={"reason": REASON}
    )

    assert response.status_code == 409, response.text
    assert error_code(response) == "INVALID_STATE_TRANSITION"


def test_suspend_of_another_clinic_patient_is_404(api: IdentityApi) -> None:
    response = api.client.post(
        status_url(OTHER_PATIENT, "suspend"),
        headers=admin(api),
        json={"reason": REASON},
    )

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"
    assert api.world.users.accounts.get(OTHER_PATIENT_USER) is None


def test_suspend_without_the_permission_is_403(api: IdentityApi) -> None:
    headers = api.bearer(
        api.staff_token(
            ADMIN, Role.CLINIC_ADMIN, frozenset({PermissionCode.PATIENTS_READ_ROSTER})
        )
    )

    response = api.client.post(
        status_url(PATIENT_ID, "suspend"), headers=headers, json={"reason": REASON}
    )

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_status_change_without_token_is_401(api: IdentityApi) -> None:
    response = api.client.post(
        status_url(PATIENT_ID, "suspend"), json={"reason": REASON}
    )

    assert response.status_code == 401


def test_reactivate_without_a_body_restores_the_patient(api: IdentityApi) -> None:
    headers = admin(api)
    api.client.post(
        status_url(PATIENT_ID, "suspend"), headers=headers, json={"reason": REASON}
    )

    response = api.client.post(status_url(PATIENT_ID, "reactivate"), headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["account_status"] == "ACTIVE"
    assert api.world.users.accounts[PATIENT_USER].status_reason is None
    own = api.client.get(OWN, headers=patient(api))
    assert own.status_code == 200, own.text


def test_reactivate_of_an_active_account_is_409(api: IdentityApi) -> None:
    response = api.client.post(
        status_url(PATIENT_ID, "reactivate"), headers=admin(api), json={}
    )

    assert response.status_code == 409
    assert error_code(response) == "INVALID_STATE_TRANSITION"


def test_deactivate_is_terminal_and_revokes_the_pending_invitation(
    api: IdentityApi,
) -> None:
    headers = admin(api)

    closed = api.client.post(
        status_url(PATIENT_ID, "deactivate"),
        headers=headers,
        json={"reason": REASON},
    )

    assert closed.status_code == 200, closed.text
    assert closed.json()["account_status"] == "DEACTIVATED"
    assert api.patient_invitations.revoked == [(PATIENT_USER, ADMIN)]
    again = api.client.post(
        status_url(PATIENT_ID, "reactivate"), headers=headers, json={}
    )
    assert again.status_code == 409
    assert error_code(again) == "INVALID_STATE_TRANSITION"


def test_deactivate_requires_a_reason(api: IdentityApi) -> None:
    response = api.client.post(
        status_url(PATIENT_ID, "deactivate"), headers=admin(api), json={}
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


# --- GET /patients/own -------------------------------------------------------


def test_patient_reads_its_own_profile(api: IdentityApi) -> None:
    response = api.client.get(OWN, headers=patient(api))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == OWN_KEYS
    assert body["id"] == str(PATIENT_ID)
    assert body["account_status"] == "ACTIVE"
    assert body["clinic"] == {"name": CLINIC.name, "simulated": True}
    assert body["target_profile"] == {
        "id": str(TEST_PROFILE.id),
        "code": TEST_PROFILE.code,
        "version": TEST_PROFILE.version,
    }
    assert body["simulated"] is True


def test_own_profile_without_consent_is_403_consent_required(
    api: IdentityApi,
) -> None:
    headers = patient(api)
    api.world.consents.records.clear()

    response = api.client.get(OWN, headers=headers)

    assert response.status_code == 403
    assert error_code(response) == "CONSENT_REQUIRED"


def test_own_profile_is_not_read_as_a_patient_id(api: IdentityApi) -> None:
    """The administrator has no own profile: the route is "own", not an id."""
    response = api.client.get(OWN, headers=admin(api))

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_own_profile_without_token_is_401(api: IdentityApi) -> None:
    response = api.client.get(OWN)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"
