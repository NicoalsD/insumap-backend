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


class StaffActivationNotification(Notification):
    """The one-time activation code of a new staff account (external channels only).

    The code is a single-use secret: it never goes in-app and never reaches a log.

    Pattern: P07 Bridge
    """

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        code: str,
        days: int,
    ) -> None:
        super().__init__(channel, messages)
        self._code = code
        self._days = days

    @override
    def compose_in_app(self) -> tuple[str, str]:
        raise ChannelNotSupportedError("notification.staff_activation")

    @override
    def compose_external(self) -> tuple[str, str]:
        return (
            self._messages.render("notification.staff_activation.subject"),
            self._messages.render(
                "notification.staff_activation.external",
                code=self._code,
                days=self._days,
            ),
        )


ACTIVATION_PATH = "activar"
"""Route of the web app that takes the code from its fragment (Seguridad 3.3)."""


class PatientActivationNotification(Notification):
    """The activation link of an imported patient, with the code in its fragment.

    The code is a single-use secret: it travels only in this external message,
    never in-app and never in a log. The fragment is not sent to the server.

    Pattern: P07 Bridge
    """

    def __init__(
        self,
        channel: NotificationChannel,
        messages: MessageCatalog,
        *,
        base_url: str,
        code: str,
        days: int,
    ) -> None:
        super().__init__(channel, messages)
        self._link = f"{base_url.rstrip('/')}/{ACTIVATION_PATH}#code={code}"
        self._days = days

    @override
    def compose_in_app(self) -> tuple[str, str]:
        raise ChannelNotSupportedError("notification.patient_activation")

    @override
    def compose_external(self) -> tuple[str, str]:
        return (
            self._messages.render("notification.patient_activation.subject"),
            self._messages.render(
                "notification.patient_activation.external",
                link=self._link,
                days=self._days,
            ),
        )


class MfaResetNotification(Notification):
    """The notice that the second factor was reset (no code, no link).

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
            self._messages.render("notification.mfa_reset.subject"),
            self._messages.render("notification.mfa_reset.external"),
        )
