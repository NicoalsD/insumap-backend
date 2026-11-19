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
    """Who receives a notification and where (``address`` is an email).

    ``clinic_id`` is the clinic of the recipient: the in-app row and its
    delivery belong to it under row level security. ``None`` for a platform
    administrator, who cannot receive in-app notifications.
    """

    user_id: UUID
    address: str = ""
    clinic_id: UUID | None = None

    def __repr__(self) -> str:
        """Identifier only: an address is personal data and never reaches a log."""
        return f"Recipient(user_id={self.user_id})"


@dataclass(frozen=True, slots=True, kw_only=True)
class InAppEntry:
    """What the in-app store keeps: a type, a message key and references.

    The table holds no text and no clinical value: the text is rendered from
    ``message_key`` when the notification is read (``alerts.notifications``).
    """

    notification_type: str
    message_key: str
    entity_type: str | None = None
    entity_id: UUID | None = None
    alert_id: UUID | None = None


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
    def deliver(
        self,
        *,
        recipient: Recipient,
        subject: str,
        body: str,
        entry: InAppEntry | None = None,
    ) -> None:
        """Hand the message to the recipient.

        ``entry`` is the structured reference of an in-app notification; the
        external channels ignore it.
        """


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
        entry: InAppEntry | None = None
        if self._channel.is_external:
            subject, body = self.compose_external()
        else:
            subject, body = self.compose_in_app()
            entry = self.in_app_entry()
        if is_demo:
            body = f"{self._messages.render(DEMO_MARK_KEY)} {body}"
        self._channel.deliver(
            recipient=recipient, subject=subject, body=body, entry=entry
        )

    @abstractmethod
    def compose_in_app(self) -> tuple[str, str]:
        """Subject and body shown inside the application."""

    def in_app_entry(self) -> InAppEntry | None:
        """The structured reference the in-app store keeps; ``None`` if it has none."""
        return None

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
