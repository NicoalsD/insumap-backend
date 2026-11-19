"""The notification that a message is waiting: the same words whoever writes.

It names no sender and carries no text: the detail is read inside the app after
signing in (Seguridad 13.4). Ordinary messages go only in-app; the alarm notice
also goes out by external channels, with no text in them.
"""

from __future__ import annotations

from typing import Final, final, override
from uuid import UUID

from insumap.application.notifications.notification import (
    InAppEntry,
    Notification,
    NotificationChannel,
    PendingNotification,
    Recipient,
)
from insumap.shared.i18n import MessageCatalog

MESSAGE_RECEIVED_KEY: Final = "notification.message_received"
MESSAGE_NOTIFICATION_TYPE: Final = "MESSAGE"
THREAD_ENTITY_TYPE: Final = "THREAD"


@final
class MessageReceivedNotification(Notification):
    """Tells the recipient that a message of their thread is waiting in the app.

    Pattern: P07 Bridge
    """

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        thread_id: UUID,
    ) -> None:
        super().__init__(channel, messages)
        self._thread_id = thread_id

    @override
    def compose_in_app(self) -> tuple[str, str]:
        return (
            self._messages.render(f"{MESSAGE_RECEIVED_KEY}.title"),
            self._messages.render(f"{MESSAGE_RECEIVED_KEY}.body"),
        )

    @override
    def compose_external(self) -> tuple[str, str]:
        return (
            self._messages.render(f"{MESSAGE_RECEIVED_KEY}.title"),
            self._messages.render(f"{MESSAGE_RECEIVED_KEY}.external"),
        )

    @override
    def in_app_entry(self) -> InAppEntry:
        return InAppEntry(
            notification_type=MESSAGE_NOTIFICATION_TYPE,
            message_key=MESSAGE_RECEIVED_KEY,
            entity_type=THREAD_ENTITY_TYPE,
            entity_id=self._thread_id,
        )


MESSAGE_ALARM_KEY: Final = "notification.message_alarm"


@final
class MessageAlarmNotification(Notification):
    """Tells the care team that a patient wrote alarm words; no text, no name.

    The in-app entry names the thread, and the detail is read after signing in.
    The external text carries no message text, no keyword and no patient name
    (Seguridad 13.4), so the hand-over to Web Push or email reveals nothing.

    Pattern: P07 Bridge
    """

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        thread_id: UUID,
    ) -> None:
        super().__init__(channel, messages)
        self._thread_id = thread_id

    @override
    def compose_in_app(self) -> tuple[str, str]:
        return (
            self._messages.render(f"{MESSAGE_ALARM_KEY}.title"),
            self._messages.render(f"{MESSAGE_ALARM_KEY}.body"),
        )

    @override
    def compose_external(self) -> tuple[str, str]:
        return (
            self._messages.render(f"{MESSAGE_ALARM_KEY}.title"),
            self._messages.render(f"{MESSAGE_ALARM_KEY}.external"),
        )

    @override
    def in_app_entry(self) -> InAppEntry:
        return InAppEntry(
            notification_type=MESSAGE_NOTIFICATION_TYPE,
            message_key=MESSAGE_ALARM_KEY,
            entity_type=THREAD_ENTITY_TYPE,
            entity_id=self._thread_id,
        )


@final
class MessageNotifier:
    """The notices of a thread, sent once the message is committed (P07, P17).

    Ordinary messages tell the other side in-app. The alarm notice goes in-app and
    by Web Push, and carries no text (RF-85).

    Pattern: P07 Bridge (uses the channels; the notifications decide the content)
    """

    def __init__(
        self,
        *,
        in_app: NotificationChannel,
        web_push: NotificationChannel,
        catalog: MessageCatalog,
    ) -> None:
        self._in_app = in_app
        self._web_push = web_push
        self._catalog = catalog

    def received(
        self, recipients: list[Recipient], *, thread_id: UUID, is_demo: bool
    ) -> None:
        """The ordinary notice: a message is waiting, in-app only."""
        for recipient in recipients:
            PendingNotification(
                notification=MessageReceivedNotification(
                    self._in_app, self._catalog, thread_id=thread_id
                ),
                recipient=recipient,
                is_demo=is_demo,
            ).send()

    def alarm(
        self, recipients: list[Recipient], *, thread_id: UUID, is_demo: bool
    ) -> None:
        """The alarm notice to the team, in-app and by Web Push, without text."""
        for channel in (self._in_app, self._web_push):
            for recipient in recipients:
                PendingNotification(
                    notification=MessageAlarmNotification(
                        channel, self._catalog, thread_id=thread_id
                    ),
                    recipient=recipient,
                    is_demo=is_demo,
                ).send()
