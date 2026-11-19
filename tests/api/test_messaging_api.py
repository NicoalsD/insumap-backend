"""Messaging and follow-up endpoints over the real app with doubles (API.md 8.12)."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.messaging.message_notifications import MESSAGE_ALARM_KEY
from insumap.domain.care_team.assignment import CareAssignment
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
DOCTOR = UUID(int=910)
STRANGER_PATIENT = UUID(int=999)
PATIENT_PERMISSIONS = frozenset(
    {PermissionCode.MESSAGES_USE_OWN, PermissionCode.FOLLOW_UPS_READ_OWN}
)
DOCTOR_PERMISSIONS = frozenset(
    {PermissionCode.MESSAGES_USE_ASSIGNED, PermissionCode.FOLLOW_UPS_MANAGE}
)
ADMIN_PERMISSIONS = frozenset({PermissionCode.CARE_TEAM_READ})
FUTURE = (NOW + timedelta(days=3)).isoformat()


def _consent(api: IdentityApi) -> None:
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=912),
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


@pytest.fixture
def api() -> IdentityApi:
    api = IdentityApi()
    api.world.permissions.by_role[Role.PATIENT] = PATIENT_PERMISSIONS
    _consent(api)
    api.records.patients.assigned.add((DOCTOR, PATIENT_ID))
    return api


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))


def admin(api: IdentityApi) -> dict[str, str]:
    return api.bearer(
        api.staff_token(UUID(int=911), Role.CLINIC_ADMIN, ADMIN_PERMISSIONS)
    )


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def _assign_doctor(api: IdentityApi) -> None:
    api.care_teams.rows[UUID(int=7000)] = CareAssignment(
        assignment_id=UUID(int=7000),
        clinic_id=CLINIC.clinic_id,
        patient_id=PATIENT_ID,
        doctor_user_id=DOCTOR,
        is_primary=True,
        assigned_by=UUID(int=911),
        assigned_at=NOW,
    )


def test_patient_sends_and_reads_own_thread(api: IdentityApi) -> None:
    _assign_doctor(api)
    sent = api.client.post(
        "/api/v1/messages", headers=patient(api), json={"body": "Tengo una duda"}
    )

    assert sent.status_code == 201, sent.text
    assert sent.json()["sender_role"] == "PATIENT"
    assert sent.json()["body"] == "Tengo una duda"
    listing = api.client.get("/api/v1/messages", headers=patient(api))
    assert listing.status_code == 200, listing.text
    assert [m["body"] for m in listing.json()["items"]] == ["Tengo una duda"]
    assert "emergencia" in listing.json()["emergency_notice"]


def test_patient_message_notifies_the_assigned_doctor_in_app(api: IdentityApi) -> None:
    _assign_doctor(api)
    api.client.post("/api/v1/messages", headers=patient(api), json={"body": "Hola"})

    delivered = api.in_app.delivered
    assert [d.recipient.user_id for d in delivered] == [DOCTOR]
    assert delivered[0].entry is not None
    assert delivered[0].entry.notification_type == "MESSAGE"
    assert "Hola" not in delivered[0].body


def test_message_listing_requires_a_token(api: IdentityApi) -> None:
    response = api.client.get("/api/v1/messages")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_clinic_admin_gets_forbidden_on_messages(api: IdentityApi) -> None:
    response = api.client.get(
        "/api/v1/messages", headers=admin(api), params={"patient_id": str(PATIENT_ID)}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_doctor_reads_an_assigned_thread(api: IdentityApi) -> None:
    _assign_doctor(api)
    api.client.post("/api/v1/messages", headers=patient(api), json={"body": "Hola"})

    response = api.client.get(
        "/api/v1/messages", headers=doctor(api), params={"patient_id": str(PATIENT_ID)}
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["sender_role"] == "PATIENT"


def test_doctor_gets_not_found_for_an_unassigned_patient(api: IdentityApi) -> None:
    response = api.client.get(
        "/api/v1/messages",
        headers=doctor(api),
        params={"patient_id": str(STRANGER_PATIENT)},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_doctor_message_without_patient_is_a_validation_error(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/messages", headers=doctor(api), json={"body": "Hola"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_message_refuses_unknown_fields(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/messages",
        headers=patient(api),
        json={"body": "Hola", "sender_role": "DOCTOR"},
    )

    assert response.status_code == 422


def test_message_body_longer_than_the_limit_is_refused(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/messages", headers=patient(api), json={"body": "x" * 1001}
    )

    assert response.status_code == 422


def test_doctor_schedules_and_closes_a_follow_up(api: IdentityApi) -> None:
    created = api.client.post(
        "/api/v1/follow-ups",
        headers=doctor(api),
        json={"patient_id": str(PATIENT_ID), "scheduled_at": FUTURE},
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "SCHEDULED"
    closed = api.client.post(
        f"/api/v1/follow-ups/{body['id']}/close",
        headers=doctor(api),
        json={"outcome": "DONE", "result_note": "Asistió y ajustamos la rutina"},
    )

    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "DONE"
    again = api.client.post(
        f"/api/v1/follow-ups/{body['id']}/close",
        headers=doctor(api),
        json={"outcome": "MISSED", "result_note": "Ya estaba cerrado"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_follow_up_in_the_past_is_refused(api: IdentityApi) -> None:
    past = (NOW - timedelta(days=1)).isoformat()
    response = api.client.post(
        "/api/v1/follow-ups",
        headers=doctor(api),
        json={"patient_id": str(PATIENT_ID), "scheduled_at": past},
    )

    assert response.status_code == 422


def test_follow_up_for_an_unassigned_patient_is_not_found(api: IdentityApi) -> None:
    response = api.client.post(
        "/api/v1/follow-ups",
        headers=doctor(api),
        json={"patient_id": str(STRANGER_PATIENT), "scheduled_at": FUTURE},
    )

    assert response.status_code == 404


def test_patient_lists_only_its_own_follow_ups(api: IdentityApi) -> None:
    created = api.client.post(
        "/api/v1/follow-ups",
        headers=doctor(api),
        json={"patient_id": str(PATIENT_ID), "scheduled_at": FUTURE},
    )
    assert created.status_code == 201, created.text

    listing = api.client.get("/api/v1/follow-ups", headers=patient(api))

    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()["items"]] == [created.json()["id"]]


def test_admin_gets_forbidden_on_follow_ups(api: IdentityApi) -> None:
    response = api.client.get("/api/v1/follow-ups", headers=admin(api))

    assert response.status_code == 403


def test_follow_up_close_rejects_a_missing_result_note(api: IdentityApi) -> None:
    response = api.client.post(
        f"/api/v1/follow-ups/{UUID(int=5)}/close",
        headers=doctor(api),
        json={"outcome": "DONE"},
    )

    assert response.status_code == 422


def test_a_message_over_the_limit_is_refused_with_retry_after(
    api: IdentityApi,
) -> None:
    _assign_doctor(api)
    headers = patient(api)
    api.world.limiter.blocked = True

    response = api.client.post(
        "/api/v1/messages", headers=headers, json={"body": "Hola"}
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert response.headers["Retry-After"]
    assert api.in_app.delivered == []


ALARM_TEXT = "Tuve una convulsión esta noche"


def test_a_sent_message_reports_its_alarm_words_and_keeps_its_text(
    api: IdentityApi,
) -> None:
    _assign_doctor(api)
    sent = api.client.post(
        "/api/v1/messages", headers=patient(api), json={"body": ALARM_TEXT}
    )

    assert sent.status_code == 201, sent.text
    assert sent.json()["alarm_keywords_detected"] == ["convulsión"]
    assert sent.json()["body"] == ALARM_TEXT


def test_a_message_without_alarm_words_reports_an_empty_list(
    api: IdentityApi,
) -> None:
    _assign_doctor(api)
    sent = api.client.post(
        "/api/v1/messages", headers=patient(api), json={"body": "Hoy estoy bien"}
    )

    assert sent.status_code == 201, sent.text
    assert sent.json()["alarm_keywords_detected"] == []


def test_the_listing_does_not_carry_the_alarm_field(api: IdentityApi) -> None:
    _assign_doctor(api)
    api.client.post("/api/v1/messages", headers=patient(api), json={"body": ALARM_TEXT})

    listing = api.client.get("/api/v1/messages", headers=patient(api))

    assert listing.status_code == 200, listing.text
    assert "alarm_keywords_detected" not in listing.json()["items"][0]


def test_the_alarm_notice_to_the_doctor_carries_no_text(api: IdentityApi) -> None:
    _assign_doctor(api)
    api.client.post("/api/v1/messages", headers=patient(api), json={"body": ALARM_TEXT})

    in_app = [
        d
        for d in api.in_app.delivered
        if d.entry is not None and d.entry.message_key == MESSAGE_ALARM_KEY
    ]
    pushed = api.web_push.delivered
    assert [d.recipient.user_id for d in in_app] == [DOCTOR]
    assert [d.recipient.user_id for d in pushed] == [DOCTOR]
    for delivered in [*in_app, *pushed]:
        assert "convulsión" not in delivered.body.lower()
        assert "esta noche" not in delivered.body
        assert "Tuve" not in delivered.body
