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
    response = create(api, platform(api), **fields)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.clinic_admins.created == []
