"""Preferences of a person: enabled channels and quiet hours (HU-35, RF-61, RF-62).

Critical alerts ignore the quiet hours; that rule belongs to the delivery of
the alerts, not to the stored preferences.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time
from enum import StrEnum
from typing import Final
from uuid import UUID

from insumap.domain.notifications.errors import InvalidNotificationSettingError

QUIET_HOURS_FIELD: Final = "body.quiet_hours"


class Channel(StrEnum):
    """Delivery channels of a notification (``alerts.notification_deliveries``)."""

    EMAIL = "EMAIL"
    WEB_PUSH = "WEB_PUSH"
    IN_APP = "IN_APP"


@dataclass(frozen=True, slots=True, kw_only=True)
class QuietHours:
    """A daily window in the local time of the clinic; it may cross midnight."""

    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise InvalidNotificationSettingError(QUIET_HOURS_FIELD, "empty_window")


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationPreferences:
    """The channels a person accepts and when they want silence."""

    user_id: UUID
    clinic_id: UUID | None
    enabled: frozenset[Channel]
    quiet_hours: QuietHours | None = None
    updated_at: datetime | None = None

    @classmethod
    def defaults(
        cls, *, user_id: UUID, clinic_id: UUID | None
    ) -> NotificationPreferences:
        """Every channel enabled and no silence: what a person has before choosing."""
        return cls(user_id=user_id, clinic_id=clinic_id, enabled=frozenset(Channel))

    def is_enabled(self, channel: Channel) -> bool:
        return channel in self.enabled

    def updated(
        self,
        *,
        channels: Mapping[Channel, bool],
        quiet_hours: QuietHours | None,
        at: datetime,
    ) -> NotificationPreferences:
        """The same person with the channels and silence the caller sent."""
        enabled = frozenset(
            channel for channel in Channel if channels.get(channel, False)
        )
        return replace(self, enabled=enabled, quiet_hours=quiet_hours, updated_at=at)
