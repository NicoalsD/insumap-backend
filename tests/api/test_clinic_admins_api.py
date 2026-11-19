"""First clinic administrator over the real app with port doubles (API.md 8.3)."""

from typing import Any
from uuid import UUID

import pytest

from insumap.domain.clinic.clinic import Clinic
from insumap.domain.common.reason import Reason
from insumap.domain.identity.codes import ActivationCode
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import NOW
from tests.support.users_fakes import FakeActivationCodes

BASE = "/api/v1/clinics"
PLATFORM = UUID(int=800)
CLINIC_ADMIN = UUID(int=801)
DEMO_CLINIC = UUID(int=10)
SUSPENDED_CLINIC = UUID(int=11)
UNKNOWN_CLINIC = UUID(int=999)
EMAIL = "admin.norte@example.test"
REASON = "Revisión de contrato con la clínica"
PLATFORM_PERMISSIONS = frozenset({PermissionCode.CLINIC_ADMINS_MANAGE})
STAFF_PERMISSIONS = frozenset({PermissionCode.CLINICS_READ})
ACTIVATION_CODE = ActivationCode(FakeActivationCodes().generate().value).formatted()


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.clinics.add(
        Clinic.create(
            clinic_id=DEMO_CLINIC,
            name="Clínica Demo",
            tax_id="900000000-1",
            timezone="America/Bogota",
            is_demo=True,
            at=NOW,
        )
    )
    api.clinics.add(
        Clinic.create(
            clinic_id=SUSPENDED_CLINIC,
            name="Clínica Sur",
            tax_id="900000002",
            timezone="America/Bogota",
            is_demo=False,
            at=NOW,
        ).suspended(reason=Reason.parse(REASON), at=NOW)
    )
    return api


def platform(
    api: IdentityApi, permissions: frozenset[PermissionCode] = PLATFORM_PERMISSIONS
) -> dict[str, str]:
    return api.bearer(api.staff_token(PLATFORM, Role.PLATFORM_ADMIN, permissions))


def staff(api: IdentityApi) -> dict[str, str]:
    return api.bearer(
        api.staff_token(CLINIC_ADMIN, Role.CLINIC_ADMIN, STAFF_PERMISSIONS)
    )


def create(
    api: IdentityApi,
    headers: dict[str, str] | None,
    clinic_id: UUID = DEMO_CLINIC,
    **fields: Any,
) -> Any:
    body = {"email": EMAIL, "full_name": "Ana Administradora"} | fields
    return api.client.post(
        f"{BASE}/{clinic_id}/admins", headers=headers or {}, json=body
    )


def test_platform_creates_the_first_admin_and_gets_no_code(api: IdentityApi) -> None:
    response = create(api, platform(api))

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"user_id", "email", "role", "invitation_expires_at"}
    assert body["role"] == "CLINIC_ADMIN"
    assert body["email"] == EMAIL
    assert response.headers["Location"] == f"/api/v1/users/{body['user_id']}"
    assert ACTIVATION_CODE not in response.text
    [admin] = api.clinic_admins.created
    assert str(admin.clinic_id) == str(DEMO_CLINIC)


def test_the_activation_code_leaves_only_by_email(api: IdentityApi) -> None:
    response = create(api, platform(api))

    [delivered] = api.mail.delivered
    assert str(delivered.recipient.user_id) == response.json()["user_id"]
    assert delivered.recipient.address == EMAIL
    assert ACTIVATION_CODE in delivered.body


def test_the_audit_row_is_written_in_the_target_clinic(api: IdentityApi) -> None:
    response = create(api, platform(api))

    [entry] = [e for e in api.audit_log.entries if e.action == "CLINIC_ADMIN_CREATED"]
    assert str(entry.clinic_id) == str(DEMO_CLINIC)
    assert str(entry.entity_id) == response.json()["user_id"]


def test_without_a_token_is_401(api: IdentityApi) -> None:
    response = create(api, None)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_clinic_admin_without_the_permission_is_403(api: IdentityApi) -> None:
    response = create(api, staff(api))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert api.clinic_admins.created == []


def test_the_platform_without_clinic_admins_manage_is_403(api: IdentityApi) -> None:
    headers = platform(api, frozenset({PermissionCode.CLINICS_MANAGE}))

    response = create(api, headers)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_an_unknown_clinic_is_404(api: IdentityApi) -> None:
    response = create(api, platform(api), clinic_id=UNKNOWN_CLINIC)

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_repeated_email_is_409_and_creates_nothing_new(api: IdentityApi) -> None:
    headers = platform(api)
    assert create(api, headers).status_code == 201

    response = create(api, headers)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "CONFLICT"
    assert len(api.clinic_admins.created) == 1
    assert len(api.mail.delivered) == 1


def test_a_suspended_clinic_is_409(api: IdentityApi) -> None:
    response = create(api, platform(api), clinic_id=SUSPENDED_CLINIC)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert api.clinic_admins.created == []


def test_an_unknown_field_is_422(api: IdentityApi) -> None:
    response = create(api, platform(api), role="PLATFORM_ADMIN")

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "fields",
    [
        {"email": "no-es-un-correo"},
        {"full_name": "   "},
        {"full_name": ""},
    ],
)
def test_an_invalid_email_or_name_is_422(
    api: IdentityApi, fields: dict[str, str]
) -> None:
    body = {"email": EMAIL, "full_name": "Ana Administradora"} | fields
    response = api.client.post(
        f"{BASE}/{DEMO_CLINIC}/admins", headers=platform(api), json=body
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.clinic_admins.created == []


ADMIN_USER = UUID(int=802)
OTHER_ADMIN_USER = UUID(int=803)
SUSPENDED_ADMIN_USER = UUID(int=804)
RESET_BASE = "/api/v1/clinics"


def seed_admins(api: IdentityApi) -> None:
    api.clinic_admins.seed(
        user_id=ADMIN_USER,
        clinic_id=DEMO_CLINIC,
        email="admin.demo@example.test",
        full_name="Ana Administradora",
    )
    api.clinic_admins.seed(
        user_id=OTHER_ADMIN_USER,
        clinic_id=SUSPENDED_CLINIC,
        email="admin.sur@example.test",
    )
    api.clinic_admins.seed(
        user_id=SUSPENDED_ADMIN_USER,
        clinic_id=DEMO_CLINIC,
        email="suspendido@example.test",
        status="SUSPENDED",
    )


def reset(
    api: IdentityApi,
    headers: dict[str, str] | None,
    user_id: UUID = ADMIN_USER,
    clinic_id: UUID = DEMO_CLINIC,
    body: dict[str, Any] | None = None,
) -> Any:
    payload = {"reason": REASON} if body is None else body
    return api.client.post(
        f"{BASE}/{clinic_id}/admins/{user_id}/reset-access",
        headers=headers or {},
        json=payload,
    )


def test_platform_resets_the_admin_with_no_body_and_no_code(api: IdentityApi) -> None:
    seed_admins(api)

    response = reset(api, platform(api))

    assert response.status_code == 204, response.text
    assert response.content == b""
    [reset_call] = api.clinic_admins.resets
    assert reset_call.user_id == ADMIN_USER
    assert reset_call.clinic_id == DEMO_CLINIC
    assert ACTIVATION_CODE not in response.text


def test_the_new_code_leaves_only_by_email_with_the_mfa_notice(
    api: IdentityApi,
) -> None:
    seed_admins(api)

    assert reset(api, platform(api)).status_code == 204

    activation, mfa_notice = api.mail.delivered
    assert str(activation.recipient.user_id) == str(ADMIN_USER)
    assert activation.recipient.address == "admin.demo@example.test"
    assert "Activa tu cuenta" in activation.subject
    assert "segundo factor" in mfa_notice.body
    assert ACTIVATION_CODE not in mfa_notice.body


def test_reset_the_audit_row_is_written_in_the_target_clinic(api: IdentityApi) -> None:
    seed_admins(api)

    assert reset(api, platform(api)).status_code == 204

    [entry] = [
        e for e in api.audit_log.entries if e.action == "CLINIC_ADMIN_ACCESS_RESET"
    ]
    assert str(entry.clinic_id) == str(DEMO_CLINIC)
    assert str(entry.entity_id) == str(ADMIN_USER)
    assert entry.reason == REASON


def test_reset_without_a_token_is_401(api: IdentityApi) -> None:
    seed_admins(api)

    response = reset(api, None)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert api.clinic_admins.resets == []


def test_reset_a_clinic_admin_without_the_permission_is_403(api: IdentityApi) -> None:
    seed_admins(api)

    response = reset(api, staff(api))

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert api.clinic_admins.resets == []


def test_reset_the_platform_without_clinic_admins_manage_is_403(
    api: IdentityApi,
) -> None:
    seed_admins(api)
    headers = platform(api, frozenset({PermissionCode.CLINICS_MANAGE}))

    response = reset(api, headers)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert api.clinic_admins.resets == []


def test_nobody_resets_his_own_access_is_403(api: IdentityApi) -> None:
    seed_admins(api)

    response = reset(api, platform(api), user_id=PLATFORM)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert api.clinic_admins.resets == []
    assert api.mail.delivered == []


def test_reset_an_unknown_clinic_is_404(api: IdentityApi) -> None:
    seed_admins(api)

    response = reset(api, platform(api), clinic_id=UNKNOWN_CLINIC)

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_admin_of_another_clinic_is_404_like_a_missing_one(
    api: IdentityApi,
) -> None:
    seed_admins(api)

    other = reset(api, platform(api), user_id=OTHER_ADMIN_USER)
    missing = reset(api, platform(api), user_id=UUID(int=999_999))

    assert other.status_code == 404, other.text
    assert missing.status_code == 404, missing.text
    assert other.json() == missing.json()
    assert api.clinic_admins.resets == []
    assert api.mail.delivered == []


def test_a_suspended_admin_is_409(api: IdentityApi) -> None:
    seed_admins(api)

    response = reset(api, platform(api), user_id=SUSPENDED_ADMIN_USER)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    assert api.clinic_admins.resets == []


@pytest.mark.parametrize(
    "body",
    [{"reason": "corto"}, {"reason": "   "}, {"reason": "x" * 501}, {}],
)
def test_a_reason_outside_10_to_500_characters_is_422(
    api: IdentityApi, body: dict[str, Any]
) -> None:
    seed_admins(api)

    response = reset(api, platform(api), body=body)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "REASON_REQUIRED"
    assert api.clinic_admins.resets == []


def test_reset_an_unknown_field_is_422(api: IdentityApi) -> None:
    seed_admins(api)

    response = reset(api, platform(api), body={"reason": REASON, "role": "X"})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.clinic_admins.resets == []
