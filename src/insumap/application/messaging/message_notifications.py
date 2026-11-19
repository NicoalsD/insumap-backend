"""The notification that a message is waiting: the same words whoever writes.

It names no sender and carries no text: the detail is read inside the app after
signing in (Seguridad 13.4). Only the in-app channel is used for messages.
"""

from __future__ import annotations

from typing import Final, final, override
from uuid import UUID

from insumap.application.notifications.notification import (
    InAppEntry,
    Notification,
    NotificationChannel,
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
