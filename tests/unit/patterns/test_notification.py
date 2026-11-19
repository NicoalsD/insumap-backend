"""Pattern: P07 Bridge. A notification decides the content; a channel delivers it."""

import logging
from collections.abc import Callable
from uuid import UUID

import pytest

from insumap.application.notifications.account_notifications import (
    EmailVerificationNotification,
    PasswordChangedNotification,
    PasswordResetNotification,
)
from insumap.application.notifications.notification import (
    ChannelNotSupportedError,
    Notification,
    NotificationChannel,
    PendingNotification,
    Recipient,
)
from insumap.infrastructure.notifications.logging_channel import LoggingEmailChannel
from insumap.shared.i18n import MessageCatalog
from tests.support.notifications import InMemoryChannel

MESSAGES = MessageCatalog.load_spanish()
RECIPIENT = Recipient(user_id=UUID(int=7), address="ana@example.test")
LINK = "https://app.example.test/reset-password#token=SECRET-TOKEN"


def reset(channel: NotificationChannel) -> Notification:
    return PasswordResetNotification(channel, MESSAGES, link=LINK, minutes=30)


def verification(channel: NotificationChannel) -> Notification:
    return EmailVerificationNotification(channel, MESSAGES, link=LINK, hours=24)


def changed(channel: NotificationChannel) -> Notification:
    return PasswordChangedNotification(channel, MESSAGES)


@pytest.mark.parametrize("build", [reset, verification])
def test_a_link_notification_goes_out_by_an_external_channel_with_its_link(
    build: Callable[[NotificationChannel], Notification],
) -> None:
    channel = InMemoryChannel(external=True)

    build(channel).send(RECIPIENT)

    [message] = channel.delivered
    assert LINK in message.body
    assert message.subject
    assert message.recipient == RECIPIENT


@pytest.mark.parametrize("build", [reset, verification])
def test_a_link_notification_is_never_composed_for_the_in_app_channel(
    build: Callable[[NotificationChannel], Notification],
) -> None:
    channel = InMemoryChannel(external=False)

    with pytest.raises(ChannelNotSupportedError):
        build(channel).send(RECIPIENT)

    assert channel.delivered == []


@pytest.mark.parametrize("external", [True, False])
def test_the_change_notice_works_on_every_channel_and_carries_no_link(
    external: bool,
) -> None:
    channel = InMemoryChannel(external=external)

    changed(channel).send(RECIPIENT)

    [message] = channel.delivered
    assert "http" not in message.body
    assert "ana@example.test" not in message.body


def test_the_same_notification_adapts_to_the_channel_without_a_class_per_pair() -> None:
    external, in_app = InMemoryChannel(external=True), InMemoryChannel(external=False)

    changed(external).send(RECIPIENT)
    changed(in_app).send(RECIPIENT)

    assert len(external.delivered) == len(in_app.delivered) == 1


def test_the_demo_mark_appears_only_for_a_demo_clinic() -> None:
    channel = InMemoryChannel()

    changed(channel).send(RECIPIENT, is_demo=False)
    changed(channel).send(RECIPIENT, is_demo=True)

    plain, demo = channel.delivered
    assert "Datos simulados" not in plain.body
    assert demo.body.startswith("Datos simulados.")


def test_the_lifetime_comes_from_the_caller_not_from_the_text() -> None:
    channel = InMemoryChannel()

    PasswordResetNotification(channel, MESSAGES, link=LINK, minutes=45).send(RECIPIENT)

    assert "45 minutos" in channel.delivered[0].body


def test_the_representation_of_a_recipient_hides_the_address() -> None:
    assert "ana@example.test" not in repr(RECIPIENT)
    assert str(RECIPIENT.user_id) in repr(RECIPIENT)


def test_a_failing_channel_is_reported_and_logged_without_the_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = InMemoryChannel(fail=True)
    pending = PendingNotification(
        notification=reset(channel), recipient=RECIPIENT, is_demo=False
    )

    with caplog.at_level(logging.ERROR):
        sent = pending.send()

    assert sent is False
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "PasswordResetNotification" in text
    assert "SECRET-TOKEN" not in text
    assert "ana@example.test" not in text


def test_a_successful_pending_notification_reports_true() -> None:
    channel = InMemoryChannel()

    sent = PendingNotification(
        notification=reset(channel), recipient=RECIPIENT, is_demo=False
    ).send()

    assert sent is True
    assert len(channel.delivered) == 1


def test_the_logging_channel_records_the_recipient_id_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = LoggingEmailChannel()

    with caplog.at_level(logging.INFO):
        reset(channel).send(RECIPIENT)

    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert channel.is_external is True
    assert str(RECIPIENT.user_id) in text
    assert "SECRET-TOKEN" not in text
    assert "ana@example.test" not in text
    assert "Restablece" not in text
