"""Email channel for local runs and the first phases: it logs, it does not send."""

from __future__ import annotations

import logging
from typing import final, override

from insumap.application.notifications.notification import (
    InAppEntry,
    NotificationChannel,
    Recipient,
)

logger = logging.getLogger(__name__)


@final
class LoggingEmailChannel(NotificationChannel):
    """Stand-in of the SMTP channel until the real one exists.

    It records that a message was handed over and to whom (identifier only).
    The subject, the body, the link and the address are never logged: a link
    carries a single-use token and an address is personal data.
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
            "Email notification handed over",
            extra={"recipient_id": str(recipient.user_id), "channel": "email"},
        )
