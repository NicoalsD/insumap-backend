"""Notification endpoints over the real app with port doubles (API.md 8.9)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.notifications.alert_notifications import ALERT_RAISED_KEY
from insumap.application.notifications.ports import NotificationView
from insumap.domain.identity.consent import ConsentAction, ConsentRecord, ConsentScope
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.notifications.push import PushEndpoint
from tests.api.identity_support import IdentityApi
from tests.support.identity_world import (
    CLINIC,
    DOCTOR_USER,
    NOTICE_ID,
    NOW,
    PASSWORD,
    PATIENT_ID,
    PATIENT_USER,
)

PATIENT_EMAIL = "paciente@example.test"
OTHER_DOCTOR = UUID(int=930)
LIST = "/api/v1/notifications"
PREFERENCES = "/api/v1/notification-preferences"
WEB_PUSH = f"{PREFERENCES}/web-push-subscription"
GOOGLE = "https://fcm.googleapis.com/fcm/send/device-1"
READ_PERMISSIONS = frozenset(
    {
        PermissionCode.NOTIFICATIONS_READ_OWN,
        PermissionCode.NOTIFICATION_PREFERENCES_MANAGE_OWN,
    }
)
ALERT_AT = datetime(2026, 11, 18, 11, 0, tzinfo=UTC)


def view(number: int, *, read: bool = False) -> NotificationView:
    return NotificationView(
        notification_id=UUID(int=3000 + number),
        notification_type="ALERT",
        message_key=ALERT_RAISED_KEY,
        entity_type="ALERT",
        entity_id=UUID(int=4000 + number),
        created_at=ALERT_AT,
        read_at=NOW if read else None,
    )


def give_consent(api: IdentityApi) -> None:
    api.world.consents.add(
        [
            ConsentRecord(
                consent_id=UUID(int=911),
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
    api.world.permissions.by_role[Role.PATIENT] = READ_PERMISSIONS
    return api


@pytest.fixture
def doctor(api: IdentityApi) -> dict[str, str]:
    token = api.staff_token(DOCTOR_USER, Role.DOCTOR, READ_PERMISSIONS)
    return api.bearer(token)


def error_code(response: object) -> str:
    return response.json()["error"]["code"]  # type: ignore[attr-defined,no-any-return]


# Authentication and permissions.


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", LIST),
        ("POST", f"{LIST}/{UUID(int=1)}/read"),
        ("GET", PREFERENCES),
        ("PUT", PREFERENCES),
        ("PUT", WEB_PUSH),
        ("DELETE", WEB_PUSH),
    ],
)
def test_every_route_needs_a_token(api: IdentityApi, method: str, path: str) -> None:
    response = api.client.request(method, path)

    assert response.status_code == 401
    assert error_code(response) == "UNAUTHENTICATED"


def test_a_staff_role_without_the_permission_is_forbidden(api: IdentityApi) -> None:
    headers = api.bearer(api.staff_token(DOCTOR_USER, Role.DOCTOR, frozenset()))

    response = api.client.get(LIST, headers=headers)

    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_a_patient_without_current_consent_is_refused(api: IdentityApi) -> None:
    login = api.client.post(
        "/api/v1/auth/login", json={"email": PATIENT_EMAIL, "password": PASSWORD}
    )
    headers = api.bearer(login.json()["access_token"])

    response = api.client.get(LIST, headers=headers)

    assert response.status_code == 403
    assert error_code(response) == "CONSENT_REQUIRED"


# Inbox.


def test_the_inbox_lists_the_callers_notifications_with_their_text(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    api.notification_store.add(view(1), recipient=DOCTOR_USER)
    api.notification_store.add(view(2), recipient=OTHER_DOCTOR)

    response = api.client.get(LIST, headers=doctor)

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    [item] = body["items"]
    assert item["id"] == str(UUID(int=3001))
    assert item["type"] == "ALERT"
    assert item["title"] == "Nueva alerta en Insumap"
    assert item["body"].startswith("Tienes una alerta nueva en Insumap.")
    assert item["entity_type"] == "ALERT"
    assert item["read_at"] is None
    assert item["simulated"] is True


def test_the_inbox_pages_with_a_cursor(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    for number in (1, 2, 3):
        api.notification_store.add(view(number), recipient=DOCTOR_USER)

    first = api.client.get(f"{LIST}?limit=2", headers=doctor).json()
    second = api.client.get(
        f"{LIST}?limit=2&cursor={first['next_cursor']}", headers=doctor
    ).json()

    assert [item["id"] for item in first["items"]] == [
        str(UUID(int=3001)),
        str(UUID(int=3002)),
    ]
    assert [item["id"] for item in second["items"]] == [str(UUID(int=3003))]
    assert second["next_cursor"] is None


def test_unread_only_hides_the_read_notifications(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    api.notification_store.add(view(1, read=True), recipient=DOCTOR_USER)
    api.notification_store.add(view(2), recipient=DOCTOR_USER)

    response = api.client.get(f"{LIST}?unread_only=true", headers=doctor)

    assert [item["id"] for item in response.json()["items"]] == [str(UUID(int=3002))]


def test_an_invalid_cursor_is_a_validation_error(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    response = api.client.get(f"{LIST}?cursor=***", headers=doctor)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


def test_marking_a_notification_read_answers_no_content_and_keeps_the_first_time(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    api.notification_store.add(view(1), recipient=DOCTOR_USER)
    path = f"{LIST}/{UUID(int=3001)}/read"

    first = api.client.post(path, headers=doctor)
    second = api.client.post(path, headers=doctor)

    assert first.status_code == 204
    assert second.status_code == 204
    assert first.content == b""
    assert api.notification_store.rows[UUID(int=3001)].read_at == NOW


def test_another_persons_notification_is_not_found(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    api.notification_store.add(view(1), recipient=OTHER_DOCTOR)

    response = api.client.post(f"{LIST}/{UUID(int=3001)}/read", headers=doctor)

    assert response.status_code == 404
    assert error_code(response) == "NOT_FOUND"
    assert api.notification_store.rows[UUID(int=3001)].read_at is None


def test_a_missing_or_malformed_notification_id_is_not_found_or_invalid(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    missing = api.client.post(f"{LIST}/{UUID(int=9)}/read", headers=doctor)
    malformed = api.client.post(f"{LIST}/no-es-uuid/read", headers=doctor)

    assert missing.status_code == 404
    assert malformed.status_code == 422


# Preferences.


def test_the_preferences_default_to_every_channel(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    response = api.client.get(PREFERENCES, headers=doctor)

    assert response.status_code == 200
    assert response.json() == {
        "channels": {"EMAIL": True, "WEB_PUSH": True, "IN_APP": True},
        "quiet_hours": None,
    }


def test_the_preferences_save_the_channels_and_the_silence(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    body = {
        "channels": {"EMAIL": False, "WEB_PUSH": True, "IN_APP": True},
        "quiet_hours": {"start": "22:00", "end": "06:30"},
    }

    response = api.client.put(PREFERENCES, headers=doctor, json=body)
    read_back = api.client.get(PREFERENCES, headers=doctor)

    assert response.status_code == 200
    assert response.json() == {
        "channels": {"EMAIL": False, "WEB_PUSH": True, "IN_APP": True},
        "quiet_hours": {"start": "22:00", "end": "06:30"},
    }
    assert read_back.json() == response.json()


def test_a_null_silence_clears_the_window(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    channels = {"EMAIL": True, "WEB_PUSH": True, "IN_APP": True}
    api.client.put(
        PREFERENCES,
        headers=doctor,
        json={"channels": channels, "quiet_hours": {"start": "22:00", "end": "06:00"}},
    )

    response = api.client.put(
        PREFERENCES, headers=doctor, json={"channels": channels, "quiet_hours": None}
    )

    assert response.json()["quiet_hours"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"channels": {"EMAIL": True, "WEB_PUSH": True}, "quiet_hours": None},
        {
            "channels": {"EMAIL": True, "WEB_PUSH": True, "IN_APP": True, "SMS": True},
            "quiet_hours": None,
        },
        {
            "channels": {"EMAIL": True, "WEB_PUSH": True, "IN_APP": True},
            "quiet_hours": None,
            "extra": 1,
        },
        {
            "channels": {"EMAIL": True, "WEB_PUSH": True, "IN_APP": True},
            "quiet_hours": {"start": "07:00", "end": "07:00"},
        },
        {
            "channels": {"EMAIL": True, "WEB_PUSH": True, "IN_APP": True},
            "quiet_hours": {"start": "25:00", "end": "07:00"},
        },
    ],
)
def test_an_invalid_preferences_body_is_a_validation_error(
    api: IdentityApi, doctor: dict[str, str], body: dict[str, object]
) -> None:
    response = api.client.put(PREFERENCES, headers=doctor, json=body)

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


# Web Push subscription.


def subscription(endpoint: str = GOOGLE) -> dict[str, object]:
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": "BPubKey-1_x", "auth": "AuthSecret_1"},
    }


def test_a_subscription_is_stored_and_removed(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    stored = api.client.put(WEB_PUSH, headers=doctor, json=subscription())
    assert stored.status_code == 204
    assert DOCTOR_USER in api.push_subscriptions.by_user
    assert (
        api.push_subscriptions.by_user[DOCTOR_USER].endpoint_hash
        == PushEndpoint.parse(
            GOOGLE, allowed_hosts=("fcm.googleapis.com",)
        ).endpoint_hash
    )

    removed = api.client.delete(WEB_PUSH, headers=doctor)

    assert removed.status_code == 204
    assert DOCTOR_USER not in api.push_subscriptions.by_user


def test_an_endpoint_outside_the_allowlist_is_refused_and_recorded(
    api: IdentityApi, doctor: dict[str, str]
) -> None:
    response = api.client.put(
        WEB_PUSH, headers=doctor, json=subscription("https://evil.example.test/push")
    )

    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"
    assert response.json()["error"]["detail"] == {
        "errors": [{"field": "body.endpoint", "type": "endpoint_rejected"}]
    }
    assert DOCTOR_USER not in api.push_subscriptions.by_user
    [event] = api.world.events.events
    assert event.event_type.value == "PUSH_ENDPOINT_REJECTED"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/device-1",
        "https://fcm.googleapis.com/fcm/send/device 1",
        "https://" + "a" * 2100,
    ],
)
def test_an_endpoint_that_is_not_https_or_too_long_is_a_validation_error(
    api: IdentityApi, doctor: dict[str, str], endpoint: str
) -> None:
    response = api.client.put(WEB_PUSH, headers=doctor, json=subscription(endpoint))

    assert response.status_code == 422
    assert DOCTOR_USER not in api.push_subscriptions.by_user


@pytest.mark.parametrize(
    "keys",
    [
        {"p256dh": "clave con espacios", "auth": "AuthSecret_1"},
        {"p256dh": "BPubKey-1_x", "auth": "x" * 65},
        {"p256dh": "BPubKey-1_x"},
    ],
)
def test_invalid_subscription_keys_are_a_validation_error(
    api: IdentityApi, doctor: dict[str, str], keys: dict[str, str]
) -> None:
    response = api.client.put(
        WEB_PUSH, headers=doctor, json={"endpoint": GOOGLE, "keys": keys}
    )

    assert response.status_code == 422
