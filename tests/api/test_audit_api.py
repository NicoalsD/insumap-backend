"""Audit endpoints over the real app with port doubles (API.md 8.13, HU-51, RF-95)."""

from uuid import UUID

import pytest

from insumap.application.audit.ports import SecurityEventKind
from insumap.application.security.events import SecurityEventType, SecuritySeverity
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.audit_fakes import access_row, audit_row, event_row
from tests.support.identity_world import CLINIC

ADMIN = UUID(int=900)
OTHER_CLINIC = UUID(int=777)
AUDIT_LOG = "/api/v1/audit-log"
DATA_ACCESS = "/api/v1/audit-log/data-access"
VERIFY = "/api/v1/audit-log/verifications"
EVENTS = "/api/v1/security-events"
CLINIC_PERMISSIONS = frozenset({PermissionCode.AUDIT_READ})
BROKEN = UUID(int=4242)


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.audit.audit_log.add(CLINIC.clinic_id, audit_row(UUID(int=1)))
    api.audit.audit_log.add(OTHER_CLINIC, audit_row(UUID(int=2)))
    api.audit.data_access.add(CLINIC.clinic_id, access_row(UUID(int=3)))
    api.audit.security_events.add(event_row(UUID(int=4), clinic_id=CLINIC.clinic_id))
    api.audit.security_events.add(event_row(UUID(int=5), clinic_id=OTHER_CLINIC))
    api.audit.security_events.add(event_row(UUID(int=6), clinic_id=None))
    return api


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, CLINIC_PERMISSIONS))


def test_audit_log_lists_only_the_clinic_without_clinical_values(
    api: IdentityApi,
) -> None:
    response = api.client.get(AUDIT_LOG, headers=admin(api))

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(UUID(int=1))]
    assert body["next_cursor"] is None
    item = body["items"][0]
    assert item["changed_fields"] == ["status"]
    assert set(item) == {
        "id",
        "occurred_at",
        "actor_user_id",
        "actor_role",
        "action",
        "entity_type",
        "entity_id",
        "reason",
        "changed_fields",
    }


def test_audit_log_filters_by_action_and_pages(api: IdentityApi) -> None:
    api.audit.audit_log.add(
        CLINIC.clinic_id, audit_row(UUID(int=10), action="ALERT_RESOLVED")
    )

    response = api.client.get(
        AUDIT_LOG,
        headers=admin(api),
        params={"action": "ALERT_RESOLVED", "limit": 1},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(UUID(int=10))]


def test_data_access_lists_the_reads_without_content(api: IdentityApi) -> None:
    response = api.client.get(DATA_ACCESS, headers=admin(api))

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["outcome"] == "GRANTED"
    assert item["purpose"] == "CARE"
    assert item["resource_type"] == "GLUCOSE_READINGS"
    assert "value_mg_dl" not in item


def test_chain_is_valid_when_intact(api: IdentityApi) -> None:
    response = api.client.post(VERIFY, headers=admin(api))

    assert response.status_code == 200
    assert response.json() == {"is_valid": True, "first_inconsistent_row_id": None}


def test_a_broken_chain_reports_the_first_inconsistent_row(api: IdentityApi) -> None:
    api.audit.chain.broken[CLINIC.clinic_id] = BROKEN

    response = api.client.post(VERIFY, headers=admin(api))

    assert response.status_code == 200
    assert response.json() == {
        "is_valid": False,
        "first_inconsistent_row_id": str(BROKEN),
    }
    recorded = [event.event_type for event in api.world.events.events]
    assert SecurityEventType.AUDIT_CHAIN_BROKEN in recorded


def test_clinic_admin_sees_only_its_own_security_events(api: IdentityApi) -> None:
    response = api.client.get(EVENTS, headers=admin(api))

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(UUID(int=4))]


def test_security_events_filter_by_type_and_severity(api: IdentityApi) -> None:
    api.audit.security_events.add(
        event_row(
            UUID(int=7),
            clinic_id=CLINIC.clinic_id,
            event_type=SecurityEventKind.AUDIT_CHAIN_BROKEN,
            severity=SecuritySeverity.CRITICAL,
        )
    )

    response = api.client.get(
        EVENTS,
        headers=admin(api),
        params={"type": "AUDIT_CHAIN_BROKEN", "severity": "CRITICAL"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(UUID(int=7))]


def test_security_events_never_show_a_full_address(api: IdentityApi) -> None:
    response = api.client.get(EVENTS, headers=admin(api))

    assert response.json()["items"][0]["ip_truncated"] == "203.0.113.0/24"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", AUDIT_LOG),
        ("get", DATA_ACCESS),
        ("post", VERIFY),
        ("get", EVENTS),
    ],
)
def test_every_route_needs_a_token(api: IdentityApi, method: str, path: str) -> None:
    response = getattr(api.client, method)(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", AUDIT_LOG),
        ("get", DATA_ACCESS),
        ("post", VERIFY),
    ],
)
def test_clinic_routes_need_the_audit_read_permission(
    api: IdentityApi, method: str, path: str
) -> None:
    headers = api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, frozenset()))

    response = getattr(api.client, method)(path, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_security_events_need_a_read_permission(api: IdentityApi) -> None:
    headers = api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, frozenset()))

    response = api.client.get(EVENTS, headers=headers)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("path", "params"),
    [
        (AUDIT_LOG, {"action": "lower_case"}),
        (AUDIT_LOG, {"from": "2026-11-19T12:00:00"}),
        (AUDIT_LOG, {"limit": 0}),
        (AUDIT_LOG, {"cursor": "!!!no-es-un-cursor!!!"}),
        (DATA_ACCESS, {"resource_type": "NOT_A_RESOURCE"}),
        (EVENTS, {"type": "NOT_AN_EVENT"}),
    ],
)
def test_invalid_filters_are_422(
    api: IdentityApi, path: str, params: dict[str, str | int]
) -> None:
    response = api.client.get(path, headers=admin(api), params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
