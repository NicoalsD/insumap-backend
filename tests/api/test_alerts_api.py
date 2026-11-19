"""Rules and alerts endpoints over the real app with port doubles (API.md 8.9)."""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest

from insumap.domain.alerts.alert import (
    Alert,
    AlertPriority,
    AlertRuleVersion,
    AlertType,
    RuleStatus,
)
from insumap.domain.alerts.escalation import parse_escalation
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.api.identity_support import IdentityApi
from tests.support.alerts_fakes import AlertsWorld
from tests.support.identity_world import (
    CLINIC,
    NOTICE_ID,
    NOW,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)

ADMIN = UUID(int=800)
DOCTOR = UUID(int=801)
PATIENT_EMAIL = "paciente@example.test"
OTHER_PATIENT = UUID(int=999)
BASE_RULES = "/api/v1/alert-rules"
BASE_ALERTS = "/api/v1/alerts"
ADMIN_PERMISSIONS = frozenset(
    {
        PermissionCode.ALERT_RULES_MANAGE,
        PermissionCode.ALERT_RULES_READ,
        PermissionCode.ALERTS_READ_SUMMARY,
    }
)
DOCTOR_PERMISSIONS = frozenset(
    {
        PermissionCode.ALERT_RULES_READ,
        PermissionCode.ALERTS_READ_ASSIGNED,
        PermissionCode.ALERTS_ACKNOWLEDGE,
        PermissionCode.ALERTS_RESOLVE,
    }
)
PATIENT_PERMISSIONS = frozenset(
    {PermissionCode.ALERTS_READ_OWN, PermissionCode.ALERTS_ACKNOWLEDGE_OWN}
)
RULE_BODY: dict[str, Any] = {
    "name": "Hipoglucemia nivel 1",
    "alert_type": "HYPOGLYCEMIA",
    "priority": "HIGH",
    "level": 1,
    "condition": {"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": 70},
    "escalation": [
        {"level": 1, "recipient": "PRIMARY_DOCTOR", "wait_minutes": 15},
    ],
}
REASON = "Ajuste de umbral tras revisión clínica"


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PATIENT_PERMISSIONS
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=811),
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


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(ADMIN, Role.CLINIC_ADMIN, ADMIN_PERMISSIONS))


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def seed_rule(world: AlertsWorld) -> AlertRuleVersion:
    rule = AlertRuleVersion(
        rule_id=UUID(int=0x500),
        clinic_id=CLINIC.clinic_id,
        code="RULE_SEEDED",
        name="Hipoglucemia",
        alert_type=AlertType.HYPOGLYCEMIA,
        level=1,
        priority=AlertPriority.HIGH,
        condition={"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": 70},
        escalation=parse_escalation(
            [{"level": 1, "recipient": "PRIMARY_DOCTOR", "wait_minutes": 15}]
        ),
        version=1,
        status=RuleStatus.ACTIVE,
        change_reason=None,
        created_by=None,
        created_at=NOW,
        activated_at=NOW,
    )
    world.rules.add(rule)
    return rule


def seed_alert(world: AlertsWorld, alert_id: int, patient: UUID) -> Alert:
    rule = seed_rule(world)
    transition = Alert.open(
        alert_id=UUID(int=alert_id),
        change_id=UUID(int=alert_id + 10_000),
        clinic_id=CLINIC.clinic_id,
        patient_id=patient,
        rule=rule,
        trigger_reading_id=None,
        evidence={"value_mg_dl": "60"},
        at=NOW - timedelta(minutes=5),
    )
    world.alerts.add(transition.alert)
    world.alerts.add_history(transition.change)
    return transition.alert


def test_admin_creates_a_rule_and_it_is_listed(api: IdentityApi) -> None:
    created = api.client.post(BASE_RULES, headers=admin(api), json=RULE_BODY)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "ACTIVE"
    assert body["version"] == 1
    assert created.headers["Location"] == f"{BASE_RULES}/{body['id']}"
    listed = api.client.get(BASE_RULES, headers=admin(api))
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]


def test_a_new_version_retires_the_active_one(api: IdentityApi) -> None:
    headers = admin(api)
    first = api.client.post(BASE_RULES, headers=headers, json=RULE_BODY).json()

    response = api.client.post(
        f"{BASE_RULES}/{first['id']}/versions",
        headers=headers,
        json={**RULE_BODY, "change_reason": REASON},
    )

    assert response.status_code == 201, response.text
    assert response.json()["version"] == 2
    detail = api.client.get(f"{BASE_RULES}/{response.json()['id']}", headers=headers)
    assert [v["version"] for v in detail.json()["versions"]] == [1, 2]
    assert [v["status"] for v in detail.json()["versions"]] == ["RETIRED", "ACTIVE"]


def test_a_rule_with_an_unknown_field_is_rejected(api: IdentityApi) -> None:
    response = api.client.post(
        BASE_RULES, headers=admin(api), json={**RULE_BODY, "extra": 1}
    )

    assert response.status_code == 422


def test_a_malformed_condition_is_rejected_before_writing(api: IdentityApi) -> None:
    body = {**RULE_BODY, "condition": {"kind": "THRESHOLD", "comparator": "EQ"}}

    response = api.client.post(BASE_RULES, headers=admin(api), json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.alerts.rules.rows == {}


def test_no_token_is_unauthenticated(api: IdentityApi) -> None:
    response = api.client.post(BASE_RULES, json=RULE_BODY)

    assert response.status_code == 401


def test_a_doctor_cannot_manage_rules(api: IdentityApi) -> None:
    response = api.client.post(BASE_RULES, headers=doctor(api), json=RULE_BODY)

    assert response.status_code == 403


def test_an_unknown_rule_is_not_found(api: IdentityApi) -> None:
    response = api.client.get(f"{BASE_RULES}/{UUID(int=1)}", headers=admin(api))

    assert response.status_code == 404


def test_doctor_lists_only_alerts_of_assigned_patients(api: IdentityApi) -> None:
    mine = seed_alert(api.alerts, 0x601, PATIENT_ID)
    seed_alert(api.alerts, 0x602, OTHER_PATIENT)
    api.alerts.alerts.assignments.add((DOCTOR, PATIENT_ID))

    response = api.client.get(BASE_ALERTS, headers=doctor(api))

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(mine.alert_id)]


def test_doctor_gets_an_alert_of_another_patient_as_not_found(api: IdentityApi) -> None:
    other = seed_alert(api.alerts, 0x603, OTHER_PATIENT)

    response = api.client.get(f"{BASE_ALERTS}/{other.alert_id}", headers=doctor(api))

    assert response.status_code == 404


def test_doctor_acknowledges_then_resolves_an_alert(api: IdentityApi) -> None:
    alert = seed_alert(api.alerts, 0x604, PATIENT_ID)
    headers = doctor(api)

    acknowledged = api.client.post(
        f"{BASE_ALERTS}/{alert.alert_id}/acknowledge", headers=headers, json={}
    )
    resolved = api.client.post(
        f"{BASE_ALERTS}/{alert.alert_id}/resolve",
        headers=headers,
        json={"note": REASON},
    )

    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["resolution_note"] == REASON
    assert [h["to_status"] for h in resolved.json()["history"]] == [
        "OPEN",
        "ACKNOWLEDGED",
        "RESOLVED",
    ]


def test_an_acknowledged_alert_cannot_be_acknowledged_again(api: IdentityApi) -> None:
    alert = seed_alert(api.alerts, 0x605, PATIENT_ID)
    headers = doctor(api)
    api.client.post(
        f"{BASE_ALERTS}/{alert.alert_id}/acknowledge", headers=headers, json={}
    )

    response = api.client.post(
        f"{BASE_ALERTS}/{alert.alert_id}/acknowledge", headers=headers, json={}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_an_open_alert_cannot_be_resolved(api: IdentityApi) -> None:
    alert = seed_alert(api.alerts, 0x606, PATIENT_ID)

    response = api.client.post(
        f"{BASE_ALERTS}/{alert.alert_id}/resolve",
        headers=doctor(api),
        json={"note": REASON},
    )

    assert response.status_code == 409


def test_patient_sees_and_acknowledges_only_its_own_alert(api: IdentityApi) -> None:
    own = seed_alert(api.alerts, 0x607, PATIENT_ID)
    headers = patient(api)

    listed = api.client.get(BASE_ALERTS, headers=headers)
    acknowledged = api.client.post(
        f"{BASE_ALERTS}/{own.alert_id}/acknowledge", headers=headers, json={}
    )

    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [str(own.alert_id)]
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["status"] == "ACKNOWLEDGED"


def test_patient_cannot_read_another_patients_alert(api: IdentityApi) -> None:
    other = seed_alert(api.alerts, 0x608, OTHER_PATIENT)

    response = api.client.get(f"{BASE_ALERTS}/{other.alert_id}", headers=patient(api))

    assert response.status_code == 404


def test_summary_is_for_the_administrator_only(api: IdentityApi) -> None:
    ok = api.client.get(f"{BASE_ALERTS}/summary", headers=admin(api))
    forbidden = api.client.get(f"{BASE_ALERTS}/summary", headers=doctor(api))

    assert ok.status_code == 200, ok.text
    assert ok.json() == {"open_count": 0, "escalated_count": 0, "by_care_team": []}
    assert forbidden.status_code == 403


@pytest.mark.parametrize("alert_id", [UUID(int=0x999)])
def test_unknown_alert_is_not_found(api: IdentityApi, alert_id: UUID) -> None:
    response = api.client.get(f"{BASE_ALERTS}/{alert_id}", headers=doctor(api))

    assert response.status_code == 404
