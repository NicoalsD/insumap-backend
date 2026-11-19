"""Reminder endpoints over the real app with port doubles (API.md 8.7)."""

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

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
    {PermissionCode.REMINDERS_MANAGE_OWN, PermissionCode.METRICS_READ_OWN}
)
DOCTOR_PERMISSIONS = frozenset({PermissionCode.REMINDERS_MANAGE_ASSIGNED})
SCHEDULE = {"local_time": "07:30", "days_of_week": [1, 2, 3, 4, 5]}


def patient_consent(api: IdentityApi) -> None:
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
    patient_consent(api)
    api.records.patients.assigned.add((DOCTOR, PATIENT_ID))
    return api


def doctor(api: IdentityApi) -> dict[str, str]:
    return api.bearer(api.staff_token(DOCTOR, Role.DOCTOR, DOCTOR_PERMISSIONS))


def patient(api: IdentityApi) -> dict[str, str]:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    return api.bearer(login.json()["access_token"])


def schedule_for(api: IdentityApi, patient_id: UUID = PATIENT_ID) -> dict[str, Any]:
    response = api.client.post(
        f"/api/v1/patients/{patient_id}/reminders",
        headers=doctor(api),
        json={"reminder_type": "MEASUREMENT", "schedule": SCHEDULE},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_doctor_schedules_a_reminder_with_its_message_key(api: IdentityApi) -> None:
    response = api.client.post(
        f"/api/v1/patients/{PATIENT_ID}/reminders",
        headers=doctor(api),
        json={"reminder_type": "MEASUREMENT", "schedule": SCHEDULE},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["patient_id"] == str(PATIENT_ID)
    assert body["message_key"] == "reminder.measurement"
    assert body["schedule"] == {
        "local_time": "07:30:00",
        "days_of_week": [1, 2, 3, 4, 5],
    }
    assert body["is_active"] is True
    assert [e.action for e in api.audit_log.entries] == ["REMINDER_CREATED"]


def test_every_day_is_a_schedule_without_weekdays(api: IdentityApi) -> None:
    response = api.client.post(
        f"/api/v1/patients/{PATIENT_ID}/reminders",
        headers=doctor(api),
        json={
            "reminder_type": "CONTROL",
            "schedule": {"local_time": "08:00", "days_of_week": None},
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["schedule"]["days_of_week"] is None


def test_weekdays_outside_the_calendar_are_refused(api: IdentityApi) -> None:
    response = api.client.post(
        f"/api/v1/patients/{PATIENT_ID}/reminders",
        headers=doctor(api),
        json={
            "reminder_type": "MEASUREMENT",
            "schedule": {"local_time": "08:00", "days_of_week": [9]},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["detail"]["errors"] == [
        {"field": "body.schedule.days_of_week", "type": "invalid_weekday"}
    ]
    assert api.reminders.rows == {}


def test_unknown_reminder_type_is_a_validation_error(api: IdentityApi) -> None:
    response = api.client.post(
        f"/api/v1/patients/{PATIENT_ID}/reminders",
        headers=doctor(api),
        json={"reminder_type": "SLEEP", "schedule": SCHEDULE},
    )

    assert response.status_code == 422


def test_doctor_lists_the_reminders_of_an_assigned_patient(api: IdentityApi) -> None:
    first = schedule_for(api)
    second = schedule_for(api)

    response = api.client.get(
        f"/api/v1/patients/{PATIENT_ID}/reminders",
        headers=doctor(api),
        params={"limit": 1},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["items"]] == [first["id"]]
    assert body["next_cursor"] is not None
    assert second["id"] != first["id"]


def test_unassigned_patient_gets_the_same_not_found_as_a_missing_one(
    api: IdentityApi,
) -> None:
    stranger = api.client.post(
        f"/api/v1/patients/{STRANGER_PATIENT}/reminders",
        headers=doctor(api),
        json={"reminder_type": "MEASUREMENT", "schedule": SCHEDULE},
    )
    missing = api.client.get(
        f"/api/v1/patients/{UUID(int=5555)}/reminders", headers=doctor(api)
    )

    assert stranger.status_code == 404
    assert missing.status_code == 404
    assert stranger.json()["error"]["code"] == "NOT_FOUND"


def test_doctor_deactivates_a_reminder_of_his_patient(api: IdentityApi) -> None:
    reminder = schedule_for(api)

    response = api.client.patch(
        f"/api/v1/patients/{PATIENT_ID}/reminders/{reminder['id']}",
        headers=doctor(api),
        json={"is_active": False},
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    assert response.json()["schedule"] == reminder["schedule"]


def test_patch_with_no_field_is_a_validation_error(api: IdentityApi) -> None:
    reminder = schedule_for(api)

    response = api.client.patch(
        f"/api/v1/patients/{PATIENT_ID}/reminders/{reminder['id']}",
        headers=doctor(api),
        json={},
    )

    assert response.status_code == 422


def test_a_reminder_of_another_patient_is_not_found(api: IdentityApi) -> None:
    reminder = schedule_for(api)
    api.records.patients.assigned.add((DOCTOR, STRANGER_PATIENT))

    response = api.client.patch(
        f"/api/v1/patients/{STRANGER_PATIENT}/reminders/{reminder['id']}",
        headers=doctor(api),
        json={"is_active": False},
    )

    assert response.status_code == 404


def test_patient_lists_and_adjusts_his_own_reminders(api: IdentityApi) -> None:
    reminder = schedule_for(api)
    headers = patient(api)

    listed = api.client.get("/api/v1/reminders", headers=headers)
    adjusted = api.client.patch(
        f"/api/v1/reminders/{reminder['id']}",
        headers=headers,
        json={"schedule": {"local_time": "09:15"}},
    )

    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [reminder["id"]]
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["schedule"]["local_time"] == "09:15:00"
    assert adjusted.json()["schedule"]["days_of_week"] is None
    assert "REMINDER_UPDATED" in [e.action for e in api.audit_log.entries]


def test_patient_cannot_adjust_a_reminder_that_is_not_his(api: IdentityApi) -> None:
    reminder = schedule_for(api)
    stored = api.reminders.rows[UUID(reminder["id"])]
    api.reminders.rows[stored.id] = replace(stored, patient_id=STRANGER_PATIENT)

    response = api.client.patch(
        f"/api/v1/reminders/{reminder['id']}",
        headers=patient(api),
        json={"is_active": False},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_patient_without_consent_is_refused(api: IdentityApi) -> None:
    reminder = schedule_for(api)
    api.world.consents.records.clear()

    response = api.client.patch(
        f"/api/v1/reminders/{reminder['id']}",
        headers=patient(api),
        json={"is_active": False},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_doctor_cannot_read_the_patient_own_listing(api: IdentityApi) -> None:
    response = api.client.get("/api/v1/reminders", headers=doctor(api))

    assert response.status_code == 403


def test_no_token_is_unauthenticated(api: IdentityApi) -> None:
    response = api.client.get(f"/api/v1/patients/{PATIENT_ID}/reminders")

    assert response.status_code == 401
