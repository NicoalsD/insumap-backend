"""The Web Push channel for now: it logs the hand-over and sends nothing.

Pattern: P07 Bridge (implementor)

The subscriptions are stored by ``PushSubscriptionRepository``. The real sender
(VAPID signing and the push service call) does not exist yet, so this adapter
makes no external call and logs only the recipient identifier, never the
endpoint, the keys or the text.
"""

from __future__ import annotations

import logging
from typing import final, override

from insumap.application.notifications.notification import (
    InAppEntry,
    NotificationChannel,
    Recipient,
)

logger = logging.getLogger(__name__)

WEB_PUSH_KIND = "web_push"


@final
class LoggingWebPushChannel(NotificationChannel):
    """Stand-in of the Web Push sender until the VAPID client exists.

    Pattern: P07 Bridge (implementor)
    """

    @property
    @override
    def is_external(self) -> bool:
        return True

    @override
    def deliver(
        self,
        *,
        recipient: Recipient,
        subject: str,
        body: str,
        entry: InAppEntry | None = None,
    ) -> None:
        del subject, body, entry
        logger.info(
            "Web Push notification handed over",
            extra={"recipient_id": str(recipient.user_id), "channel": WEB_PUSH_KIND},
        )
