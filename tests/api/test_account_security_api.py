"""``POST /auth/mfa/recovery-codes`` and ``POST /auth/password/change``."""

from typing import Any
from uuid import UUID

import pytest

from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from tests.api.identity_support import IdentityApi
from tests.support.identity_fakes import VALID_TOTP
from tests.support.identity_world import (
    CLINIC,
    NEW_PASSWORD,
    NOTICE_ID,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)

PATIENT = {"email": "paciente@example.test", "password": PASSWORD}
DOCTOR = {"email": "medico@example.test", "password": PASSWORD}
NEW_DOCTOR = {"email": "nuevo@example.test", "password": PASSWORD}
RECOVERY = "/api/v1/auth/mfa/recovery-codes"
CHANGE = "/api/v1/auth/password/change"


def error_code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def doctor_headers(api: IdentityApi) -> dict[str, str]:
    challenge = api.client.post("/api/v1/auth/login", json=DOCTOR).json()[
        "challenge_token"
    ]
    token = api.client.post(
        "/api/v1/auth/mfa/verify",
        json={"challenge_token": challenge, "code": VALID_TOTP},
    ).json()["access_token"]
    return api.bearer(token)


def patient_headers(api: IdentityApi, *, accepted: bool = True) -> dict[str, str]:
    if accepted:
        api.world.consents.records.append(
            ConsentRecord(
                consent_id=UUID(int=5),
                clinic_id=CLINIC.clinic_id,
                patient_id=PATIENT_ID,
                privacy_notice_version_id=NOTICE_ID,
                scope=ConsentScope.SENSITIVE_DATA_PROCESSING,
                action=ConsentAction.ACCEPTED,
                occurred_at=api.world.clock.now(),
                recorded_by=PATIENT_USER,
            )
        )
    token = api.client.post("/api/v1/auth/login", json=PATIENT).json()["access_token"]
    return api.bearer(token)


# Recovery codes.


def test_a_doctor_regenerates_the_codes_and_the_action_is_audited() -> None:
    api = IdentityApi()
    headers = doctor_headers(api)
    api.world.totp.STEP += 1  # a TOTP step is accepted once: the login used this one

    response = api.client.post(RECOVERY, headers=headers, json={"code": VALID_TOTP})

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert len(response.json()["recovery_codes"]) == 10
    [entry] = api.audit_log.entries
    assert entry.action == "MFA_RECOVERY_CODES_REGENERATED"
    assert "recovery_codes" in entry.changed_fields


def test_a_wrong_totp_is_401_invalid_credentials_and_leaves_no_audit_row() -> None:
    api = IdentityApi()

    response = api.client.post(
        RECOVERY, headers=doctor_headers(api), json={"code": "000000"}
    )

    assert response.status_code == 401
    assert error_code(response) == "INVALID_CREDENTIALS"
    assert api.audit_log.entries == []


@pytest.mark.parametrize("payload", [{}, {"code": "12"}, {"code": "123456", "x": 1}])
def test_recovery_codes_validate_the_body(payload: dict[str, Any]) -> None:
    api = IdentityApi()

    response = api.client.post(RECOVERY, headers=doctor_headers(api), json=payload)

    assert response.status_code == 422


def test_recovery_codes_need_a_session_with_the_second_factor() -> None:
    api = IdentityApi()
    enrolling = api.client.post("/api/v1/auth/login", json=NEW_DOCTOR).json()

    anonymous = api.client.post(RECOVERY, json={"code": VALID_TOTP})
    without_otp = api.client.post(
        RECOVERY,
        headers=api.bearer(enrolling["access_token"]),
        json={"code": VALID_TOTP},
    )
    patient = api.client.post(
        RECOVERY, headers=patient_headers(api), json={"code": VALID_TOTP}
    )

    assert error_code(anonymous) == "UNAUTHENTICATED"
    assert error_code(without_otp) == "MFA_REQUIRED"
    assert error_code(patient) == "FORBIDDEN"


# Password change.


def test_changing_the_password_returns_a_new_session_and_ends_the_old_one() -> None:
    api = IdentityApi()
    old = patient_headers(api)

    response = api.client.post(
        CHANGE,
        headers=old,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "AUTHENTICATED"
    assert "__Secure-insumap_rt" in response.headers["set-cookie"]
    stale = api.client.get("/api/v1/auth/current-user", headers=old)
    fresh = api.client.get(
        "/api/v1/auth/current-user", headers=api.bearer(body["access_token"])
    )
    assert error_code(stale) == "SESSION_REVOKED"
    assert fresh.status_code == 200
    login = api.client.post(
        "/api/v1/auth/login", json={**PATIENT, "password": NEW_PASSWORD}
    )
    assert login.status_code == 200
    assert [entry.action for entry in api.audit_log.entries] == ["PASSWORD_CHANGED"]
    assert NEW_PASSWORD not in repr(api.audit_log.entries)


def test_a_wrong_current_password_is_401_and_a_weak_new_one_is_422() -> None:
    api = IdentityApi()
    headers = patient_headers(api)

    wrong = api.client.post(
        CHANGE,
        headers=headers,
        json={"current_password": "wrong password!!", "new_password": NEW_PASSWORD},
    )
    weak = api.client.post(
        CHANGE,
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "short"},
    )

    assert error_code(wrong) == "INVALID_CREDENTIALS"
    assert weak.status_code == 422
    codes = [item["code"] for item in weak.json()["error"]["detail"]["errors"]]
    assert "PASSWORD_TOO_SHORT" in codes
    assert NEW_PASSWORD not in weak.text
    assert api.audit_log.entries == []


def test_password_change_validates_the_body_and_needs_a_session() -> None:
    api = IdentityApi()

    missing = api.client.post(
        CHANGE, headers=patient_headers(api), json={"current_password": PASSWORD}
    )
    anonymous = api.client.post(
        CHANGE, json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )

    assert missing.status_code == 422
    assert anonymous.status_code == 401


def test_a_patient_with_a_pending_consent_gets_consent_required() -> None:
    api = IdentityApi()

    response = api.client.post(
        CHANGE,
        headers=patient_headers(api, accepted=False),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 403
    assert error_code(response) == "CONSENT_REQUIRED"
