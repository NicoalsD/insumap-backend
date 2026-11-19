"""The notification that an alert was raised: the same words in every channel.

It names the alert and nothing else: no value, no level, no diagnosis (Seguridad
13.4). The detail is read inside the app after signing in.
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

ALERT_RAISED_KEY: Final = "notification.alert_raised"
ALERT_NOTIFICATION_TYPE: Final = "ALERT"
ALERT_ENTITY_TYPE: Final = "ALERT"


@final
class AlertRaisedNotification(Notification):
    """Tells the recipient that an alert of the clinic is waiting for them.

    Pattern: P07 Bridge
    """

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        alert_id: UUID,
    ) -> None:
        super().__init__(channel, messages)
        self._alert_id = alert_id

    @override
    def compose_in_app(self) -> tuple[str, str]:
        return (
            self._messages.render(f"{ALERT_RAISED_KEY}.title"),
            self._messages.render(f"{ALERT_RAISED_KEY}.body"),
        )

    @override
    def compose_external(self) -> tuple[str, str]:
        return (
            self._messages.render(f"{ALERT_RAISED_KEY}.title"),
            self._messages.render(f"{ALERT_RAISED_KEY}.external"),
        )

    @override
    def in_app_entry(self) -> InAppEntry:
        return InAppEntry(
            notification_type=ALERT_NOTIFICATION_TYPE,
            message_key=ALERT_RAISED_KEY,
            entity_type=ALERT_ENTITY_TYPE,
            entity_id=self._alert_id,
            alert_id=self._alert_id,
        )
