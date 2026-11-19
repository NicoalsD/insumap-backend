"""Pattern: P07 Bridge. The staff notifications compose; the channel only delivers."""

from uuid import UUID

import pytest

from insumap.application.notifications.account_notifications import (
    MfaResetNotification,
    StaffActivationNotification,
)
from insumap.application.notifications.notification import (
    ChannelNotSupportedError,
    Recipient,
)
from insumap.shared.i18n import MessageCatalog
from tests.support.notifications import InMemoryChannel

MESSAGES = MessageCatalog.load_spanish()
RECIPIENT = Recipient(user_id=UUID(int=8), address="nueva@example.test")
CODE = "ABCD-EFGH-JKMN-PQRS"
DEMO_MARK = "Datos simulados."


def activation(channel: InMemoryChannel) -> StaffActivationNotification:
    return StaffActivationNotification(channel, MESSAGES, code=CODE, days=7)


def test_the_activation_code_never_goes_in_app() -> None:
    notification = activation(InMemoryChannel(external=False))

    with pytest.raises(ChannelNotSupportedError):
        notification.compose_in_app()


def test_the_external_body_carries_the_code_and_the_days() -> None:
    channel = InMemoryChannel(external=True)

    activation(channel).send(RECIPIENT)

    [delivered] = channel.delivered
    assert CODE in delivered.body
    assert "7 días" in delivered.body
    assert delivered.recipient == RECIPIENT


def test_a_demo_clinic_marks_the_activation_email() -> None:
    channel = InMemoryChannel(external=True)

    activation(channel).send(RECIPIENT, is_demo=True)

    [delivered] = channel.delivered
    assert delivered.body.startswith(DEMO_MARK)


def test_the_mfa_reset_notice_composes_for_both_channels_without_a_secret() -> None:
    for external in (True, False):
        channel = InMemoryChannel(external=external)

        MfaResetNotification(channel, MESSAGES).send(RECIPIENT)

        [delivered] = channel.delivered
        assert delivered.subject == MESSAGES.render("notification.mfa_reset.subject")
        assert "#token=" not in delivered.body
        assert CODE not in delivered.body
