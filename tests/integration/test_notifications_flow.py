"""Notifications over PostgreSQL 18: real grants, RLS and the in-app channel."""

from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import psycopg
import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from insumap.application.common.unit_of_work import TransactionalUnitOfWorkPort
from insumap.application.events.publisher import InProcessDomainEventPublisher
from insumap.application.notifications.alert_notifications import (
    AlertRaisedNotification,
)
from insumap.application.notifications.notification import Recipient
from insumap.infrastructure.identity_adapters import build_engine
from insumap.infrastructure.notification_adapters import build_notification_adapters
from insumap.infrastructure.persistence.transactions import (
    CurrentSession,
    SqlTransactionFactory,
)
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import SystemClock
from tests.support.db_seed import ADMIN_EMAIL, DEMO_PASSWORD, DOCTOR_EMAIL, DemoWorld
from tests.support.identity_fakes import FakeIds
from tests.support.settings import make_settings

pytestmark = pytest.mark.integration

LIST = "/api/v1/notifications"
PREFERENCES = "/api/v1/notification-preferences"
WEB_PUSH = f"{PREFERENCES}/web-push-subscription"
GOOGLE = "https://fcm.googleapis.com/fcm/send/integration-device"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _staff_headers(api: TestClient, email: str) -> dict[str, str]:
    """Enroll MFA on the first sign in, then sign in with a recovery code."""
    first = api.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    headers = _bearer(first.json()["access_token"])
    started = api.post("/api/v1/auth/mfa/enrollment", headers=headers)
    secret = parse_qs(urlsplit(started.json()["otpauth_uri"]).query)["secret"][0]
    confirmed = api.post(
        "/api/v1/auth/mfa/enrollment/confirm",
        headers=headers,
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert confirmed.status_code == 200, confirmed.text
    second = api.post(
        "/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    verified = api.post(
        "/api/v1/auth/mfa/verify",
        json={
            "challenge_token": second.json()["challenge_token"],
            "code": confirmed.json()["recovery_codes"][0],
        },
    )
    assert verified.status_code == 200, verified.text
    return _bearer(verified.json()["access_token"])


@pytest.fixture
def doctor(api: TestClient, demo_world: DemoWorld) -> dict[str, str]:
    del demo_world
    return _staff_headers(api, DOCTOR_EMAIL)


@pytest.fixture
def admin(api: TestClient, demo_world: DemoWorld) -> dict[str, str]:
    del demo_world
    return _staff_headers(api, ADMIN_EMAIL)


@pytest.fixture
def app_engine(app_url: str) -> Iterator[Engine]:
    engine = build_engine(make_settings(database_url=app_url))
    yield engine
    engine.dispose()


def _in_app_alert(migrated_url: str, app_engine: Engine, demo_world: DemoWorld) -> UUID:
    """Create a real alert (superuser, as the scheduler will) and notify the doctor.

    The notification goes through the in-app channel of the P07 bridge, in the
    SYSTEM context under RLS, as the application does after the commit.
    """
    with psycopg.connect(migrated_url, autocommit=True) as conn:
        patient_id = conn.execute(
            "SELECT id FROM clinic.patients WHERE clinic_id = %s LIMIT 1",
            (demo_world.clinic_id,),
        ).fetchone()
        assert patient_id is not None
        rule_id = conn.execute(
            "INSERT INTO alerts.alert_rules (clinic_id, code, name, alert_type,"
            " level, priority, definition, escalation, version, status)"
            " VALUES (%s, 'TEST_NOTIFY_RULE', 'Regla de prueba', 'HYPOGLYCEMIA',"
            " 1, 'HIGH', '{}'::jsonb, '[]'::jsonb, 1, 'DRAFT') RETURNING id",
            (demo_world.clinic_id,),
        ).fetchone()[0]  # type: ignore[index]
        alert_id = conn.execute(
            "INSERT INTO alerts.alerts (clinic_id, patient_id, rule_id,"
            " alert_type, priority) VALUES (%s, %s, %s, 'HYPOGLYCEMIA', 'HIGH')"
            " RETURNING id",
            (demo_world.clinic_id, patient_id[0], rule_id),
        ).fetchone()[0]  # type: ignore[index]

    current = CurrentSession()
    channels = build_notification_adapters(
        current=current,
        unit_of_work=TransactionalUnitOfWorkPort(
            SqlTransactionFactory(app_engine, current), InProcessDomainEventPublisher()
        ),
        ids=FakeIds(),
        clock=SystemClock.instance(),
    )
    recipient = Recipient(
        user_id=demo_world.doctor_user_id, clinic_id=demo_world.clinic_id
    )
    AlertRaisedNotification(
        channels.in_app, MessageCatalog.load_spanish(), alert_id=alert_id
    ).send(recipient)
    return UUID(str(alert_id))


def test_an_alert_notification_reaches_the_doctor_inbox_as_text(
    migrated_url: str,
    app_engine: Engine,
    demo_world: DemoWorld,
    api: TestClient,
    doctor: dict[str, str],
) -> None:
    alert_id = _in_app_alert(migrated_url, app_engine, demo_world)

    listing = api.get(LIST, headers=doctor).json()

    [item] = listing["items"]
    assert item["type"] == "ALERT"
    assert item["entity_type"] == "ALERT"
    assert item["entity_id"] == str(alert_id)
    assert item["title"] == "Nueva alerta en Insumap"
    assert "mg/dL" not in item["body"]


def test_the_in_app_delivery_is_stored_as_sent(
    migrated_url: str,
    app_engine: Engine,
    demo_world: DemoWorld,
) -> None:
    _in_app_alert(migrated_url, app_engine, demo_world)

    with psycopg.connect(migrated_url) as conn:
        status, channel = conn.execute(
            "SELECT status, channel FROM alerts.notification_deliveries"
            " WHERE clinic_id = %s",
            (demo_world.clinic_id,),
        ).fetchone()  # type: ignore[misc]

    assert (status, channel) == ("SENT", "IN_APP")


def test_marking_read_is_visible_on_the_next_listing(
    migrated_url: str,
    app_engine: Engine,
    demo_world: DemoWorld,
    api: TestClient,
    doctor: dict[str, str],
) -> None:
    _in_app_alert(migrated_url, app_engine, demo_world)
    [item] = api.get(LIST, headers=doctor).json()["items"]

    marked = api.post(f"{LIST}/{item['id']}/read", headers=doctor)
    unread = api.get(f"{LIST}?unread_only=true", headers=doctor).json()

    assert marked.status_code == 204
    assert unread["items"] == []


def test_another_account_cannot_see_or_mark_the_notification(
    migrated_url: str,
    app_engine: Engine,
    demo_world: DemoWorld,
    api: TestClient,
    doctor: dict[str, str],
    admin: dict[str, str],
) -> None:
    _in_app_alert(migrated_url, app_engine, demo_world)
    [item] = api.get(LIST, headers=doctor).json()["items"]

    listing = api.get(LIST, headers=admin).json()
    attempt = api.post(f"{LIST}/{item['id']}/read", headers=admin)

    assert listing["items"] == []
    assert attempt.status_code == 404
    assert attempt.json()["error"]["code"] == "NOT_FOUND"


def test_preferences_default_then_save_under_rls(
    api: TestClient, doctor: dict[str, str]
) -> None:
    assert api.get(PREFERENCES, headers=doctor).json()["quiet_hours"] is None

    body = {
        "channels": {"EMAIL": True, "WEB_PUSH": False, "IN_APP": True},
        "quiet_hours": {"start": "22:00", "end": "06:00"},
    }
    saved = api.put(PREFERENCES, headers=doctor, json=body)

    assert saved.status_code == 200
    assert api.get(PREFERENCES, headers=doctor).json() == saved.json()


def test_a_web_push_subscription_is_stored_with_encrypted_auth(
    migrated_url: str,
    api: TestClient,
    doctor: dict[str, str],
    demo_world: DemoWorld,
) -> None:
    body: dict[str, Any] = {
        "endpoint": GOOGLE,
        "keys": {"p256dh": "BPubKey-1_x", "auth": "AuthSecret_1"},
    }

    stored = api.put(WEB_PUSH, headers=doctor, json=body)

    assert stored.status_code == 204
    with psycopg.connect(migrated_url) as conn:
        plain_auth = conn.execute(
            "SELECT count(*) FROM alerts.push_subscriptions"
            " WHERE user_id = %s AND auth_ciphertext = %s",
            (demo_world.doctor_user_id, b"AuthSecret_1"),
        ).fetchone()
    assert plain_auth == (0,)

    removed = api.delete(WEB_PUSH, headers=doctor)

    assert removed.status_code == 204
    with psycopg.connect(migrated_url) as conn:
        remaining = conn.execute(
            "SELECT count(*) FROM alerts.push_subscriptions WHERE user_id = %s",
            (demo_world.doctor_user_id,),
        ).fetchone()
    assert remaining == (0,)


def test_a_rejected_endpoint_is_recorded_as_a_security_event(
    migrated_url: str,
    api: TestClient,
    doctor: dict[str, str],
    demo_world: DemoWorld,
) -> None:
    body = {
        "endpoint": "https://evil.example.test/push",
        "keys": {"p256dh": "BPubKey-1_x", "auth": "AuthSecret_1"},
    }

    response = api.put(WEB_PUSH, headers=doctor, json=body)

    assert response.status_code == 422
    with psycopg.connect(migrated_url) as conn:
        events = conn.execute(
            "SELECT count(*) FROM iam.security_events"
            " WHERE event_type = 'PUSH_ENDPOINT_REJECTED' AND user_id = %s",
            (demo_world.doctor_user_id,),
        ).fetchone()
    assert events == (1,)
