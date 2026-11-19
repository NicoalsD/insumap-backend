"""Notifications about the account: reset link, verification link, change notice.

The links carry a single-use token, so they travel only by external channels
(email) and are never composed for the in-app channel.
"""

from __future__ import annotations

from typing import override

from insumap.application.notifications.notification import (
    ChannelNotSupportedError,
    Notification,
    NotificationChannel,
)
from insumap.shared.i18n import MessageCatalog


class _LinkNotification(Notification):
    """Base of the notifications that carry a single-use link."""

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        key: str,
        link: str,
        lifetime: int,
    ) -> None:
        super().__init__(channel, messages)
        self._key = key
        self._link = link
        self._lifetime = lifetime

    @override
    def compose_in_app(self) -> tuple[str, str]:
        raise ChannelNotSupportedError(self._key)

    @override
    def compose_external(self) -> tuple[str, str]:
        return (
            self._messages.render(f"{self._key}.subject"),
            self._messages.render(
                f"{self._key}.external", link=self._link, lifetime=self._lifetime
            ),
        )


class PasswordResetNotification(_LinkNotification):
    """The link to choose a new password (30 minutes, single use).

    Pattern: P07 Bridge
    """

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        link: str,
        minutes: int,
    ) -> None:
        super().__init__(
            channel,
            messages,
            key="notification.password_reset",
            link=link,
            lifetime=minutes,
        )


class EmailVerificationNotification(_LinkNotification):
    """The link that confirms the email of the account (24 hours, single use).

    Pattern: P07 Bridge
    """

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        link: str,
        hours: int,
    ) -> None:
        super().__init__(
            channel,
            messages,
            key="notification.email_verification",
            link=link,
            lifetime=hours,
        )


class PasswordChangedNotification(Notification):
    """The notice to the holder that the password was reset (no link, no secret).

    Pattern: P07 Bridge
    """

    @override
    def compose_in_app(self) -> tuple[str, str]:
        return self._compose()

    @override
    def compose_external(self) -> tuple[str, str]:
        return self._compose()

    def _compose(self) -> tuple[str, str]:
        return (
            self._messages.render("notification.password_changed.subject"),
            self._messages.render("notification.password_changed.external"),
        )
