"""Pattern: P07 Bridge. The alert notification is the same on every channel.

The notification decides the words and the in-app reference; the channel only
stores or hands over. Tests use the doubles of the ports, never a database.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.common.unit_of_work import TransactionContext
from insumap.application.notifications.alert_notifications import (
    ALERT_RAISED_KEY,
    AlertRaisedNotification,
)
from insumap.application.notifications.notification import (
    ChannelNotSupportedError,
    PendingNotification,
    Recipient,
)
from insumap.domain.identity.roles import Role
from insumap.infrastructure.notifications.in_app_channel import InAppNotificationChannel
from insumap.infrastructure.notifications.logging_channel import LoggingEmailChannel
from insumap.infrastructure.notifications.web_push_channel import LoggingWebPushChannel
from insumap.shared.i18n import MessageCatalog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds, FakeUnitOfWorkPort
from tests.support.notification_fakes import InMemoryNotificationStore
from tests.support.notifications import InMemoryChannel

MESSAGES = MessageCatalog.load_spanish()
NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
CLINIC = UUID(int=50)
RECIPIENT = Recipient(
    user_id=UUID(int=51), address="medica@example.test", clinic_id=CLINIC
)
ALERT = UUID(int=52)
SECRET_VALUE = "glucosa 42 mg/dL"


def alert(channel: object) -> AlertRaisedNotification:
    return AlertRaisedNotification(channel, MESSAGES, alert_id=ALERT)  # type: ignore[arg-type]


def test_the_in_app_channel_receives_the_structured_reference_not_only_text() -> None:
    channel = InMemoryChannel(external=False)

    alert(channel).send(RECIPIENT)

    [message] = channel.delivered
    assert message.entry is not None
    assert message.entry.notification_type == "ALERT"
    assert message.entry.message_key == ALERT_RAISED_KEY
    assert message.entry.alert_id == ALERT
    assert message.entry.entity_id == ALERT


def test_the_external_channels_get_the_short_text_and_no_reference() -> None:
    channel = InMemoryChannel(external=True)

    alert(channel).send(RECIPIENT)

    [message] = channel.delivered
    assert message.entry is None
    assert message.body == MESSAGES.render(f"{ALERT_RAISED_KEY}.external")
    assert "Tienes una alerta nueva en Insumap" in message.body


def test_no_channel_carries_a_clinical_value() -> None:
    for external in (True, False):
        channel = InMemoryChannel(external=external)

        alert(channel).send(RECIPIENT)

        [message] = channel.delivered
        assert SECRET_VALUE not in message.body
        assert "mg/dL" not in message.body


def test_the_demo_mark_precedes_the_external_text_of_a_demo_clinic() -> None:
    channel = InMemoryChannel(external=True)

    alert(channel).send(RECIPIENT, is_demo=True)

    [message] = channel.delivered
    assert message.body.startswith("Datos simulados.")


def test_the_in_app_channel_stores_the_notification_and_its_sent_delivery() -> None:
    store = InMemoryNotificationStore()
    uow = FakeUnitOfWorkPort()
    channel = InAppNotificationChannel(
        uow=uow, store=store, ids=FakeIds(), clock=FixedClock(NOW)
    )

    alert(channel).send(RECIPIENT)

    [row] = store.rows.values()
    assert row.notification_type == "ALERT"
    assert row.message_key == ALERT_RAISED_KEY
    assert row.entity_id == ALERT
    assert row.created_at == NOW
    assert row.read_at is None
    assert store.recipients[row.notification_id] == RECIPIENT.user_id
    [(delivery_id, notification_id, channel_name)] = store.deliveries
    assert notification_id == row.notification_id
    assert channel_name == "IN_APP"
    assert delivery_id != row.notification_id


def test_the_in_app_write_runs_in_the_system_context_for_the_clinic() -> None:
    uow = FakeUnitOfWorkPort()
    channel = InAppNotificationChannel(
        uow=uow,
        store=InMemoryNotificationStore(),
        ids=FakeIds(),
        clock=FixedClock(NOW),
    )

    alert(channel).send(RECIPIENT)

    assert uow.contexts[-1] == TransactionContext(clinic_id=CLINIC, role=Role.SYSTEM)
    assert uow.commits == 1


def test_a_recipient_without_clinic_is_refused_by_the_in_app_channel() -> None:
    store = InMemoryNotificationStore()
    channel = InAppNotificationChannel(
        uow=FakeUnitOfWorkPort(),
        store=store,
        ids=FakeIds(),
        clock=FixedClock(NOW),
    )
    platform_admin = Recipient(user_id=UUID(int=53))

    with pytest.raises(ChannelNotSupportedError):
        alert(channel).send(platform_admin)

    assert store.rows == {}


def test_a_failed_in_app_write_is_logged_and_reported_without_the_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class BrokenStore(InMemoryNotificationStore):
        def store(self, **_: object) -> None:
            raise ConnectionError("database is down")

    channel = InAppNotificationChannel(
        uow=FakeUnitOfWorkPort(),
        store=BrokenStore(),
        ids=FakeIds(),
        clock=FixedClock(NOW),
    )
    pending = PendingNotification(
        notification=alert(channel), recipient=RECIPIENT, is_demo=False
    )

    with caplog.at_level(logging.ERROR):
        sent = pending.send()

    assert sent is False
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "AlertRaisedNotification" in text
    assert str(RECIPIENT.user_id) in text
    assert "Tienes una alerta" not in text


def test_the_web_push_channel_logs_the_identifier_and_sends_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = LoggingWebPushChannel()

    with caplog.at_level(logging.INFO):
        alert(channel).send(RECIPIENT)

    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert channel.is_external is True
    assert str(RECIPIENT.user_id) in text
    assert "web_push" in text
    assert "medica@example.test" not in text
    assert "Tienes una alerta" not in text


def test_the_email_logging_channel_still_accepts_the_same_notification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO):
        alert(LoggingEmailChannel()).send(RECIPIENT)

    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert str(RECIPIENT.user_id) in text
    assert "medica@example.test" not in text
