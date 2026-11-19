"""Bridge between a notification and its delivery channel (P07).

The notification decides the content; the channel only delivers it. A channel
never builds text and a notification never talks to SMTP or a push service.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Final, final
from uuid import UUID

from insumap.shared.i18n import MessageCatalog

logger = logging.getLogger(__name__)

DEMO_MARK_KEY: Final = "demo.mark"


@dataclass(frozen=True, slots=True, kw_only=True)
class Recipient:
    """Who receives a notification and where (``address`` is an email)."""

    user_id: UUID
    address: str = ""

    def __repr__(self) -> str:
        """Identifier only: an address is personal data and never reaches a log."""
        return f"Recipient(user_id={self.user_id})"


@final
class ChannelNotSupportedError(ValueError):
    """A notification asked for a channel kind it cannot be composed for."""


class NotificationChannel(ABC):
    """Implementor of the bridge: delivers a ready message, nothing else."""

    @property
    @abstractmethod
    def is_external(self) -> bool:
        """``True`` for channels that leave the app (email, push)."""

    @abstractmethod
    def deliver(self, *, recipient: Recipient, subject: str, body: str) -> None:
        """Hand the message to the recipient."""


class Notification(ABC):
    """Abstraction of the bridge: it owns the content, not the delivery.

    Pattern: P07 Bridge
    """

    def __init__(self, channel: NotificationChannel, messages: MessageCatalog) -> None:
        self._channel = channel
        self._messages = messages

    @final
    def send(self, recipient: Recipient, *, is_demo: bool = False) -> None:
        """Compose for the kind of channel and deliver; demo clinics get the mark."""
        if self._channel.is_external:
            subject, body = self.compose_external()
        else:
            subject, body = self.compose_in_app()
        if is_demo:
            body = f"{self._messages.render(DEMO_MARK_KEY)} {body}"
        self._channel.deliver(recipient=recipient, subject=subject, body=body)

    @abstractmethod
    def compose_in_app(self) -> tuple[str, str]:
        """Subject and body shown inside the application."""

    @abstractmethod
    def compose_external(self) -> tuple[str, str]:
        """Subject and body for email and push: no clinical data, names or diagnoses."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingNotification:
    """A notification prepared inside a transaction and sent after its commit.

    Nothing leaves the system until the data it announces is durable.
    """

    notification: Notification
    recipient: Recipient
    is_demo: bool

    def send(self) -> bool:
        """Deliver now; a channel failure is logged and reported, never raised.

        The data the notification announces is already committed, so a failed
        delivery must not turn the request into an error. The log carries the
        notification type and the recipient id, never the content.
        """
        try:
            self.notification.send(self.recipient, is_demo=self.is_demo)
        except Exception as error:
            # No trace: it could repeat the address or the link.
            logger.error(
                "Notification delivery failed",
                extra={
                    "notification_type": type(self.notification).__name__,
                    "recipient_id": str(self.recipient.user_id),
                    "error_type": type(error).__name__,
                },
            )
            return False
        return True
