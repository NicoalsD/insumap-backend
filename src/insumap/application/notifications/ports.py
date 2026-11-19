"""Ports of the notification use cases and of the in-app channel."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.application.notifications.notification import InAppEntry
from insumap.domain.notifications.preferences import NotificationPreferences


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationView:
    """An in-app notification as stored: keys and references, no rendered text."""

    notification_id: UUID
    notification_type: str
    message_key: str
    entity_type: str | None
    entity_id: UUID | None
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PushSubscriptionRecord:
    """A Web Push subscription ready to store: the auth secret is already encrypted."""

    subscription_id: UUID
    clinic_id: UUID | None
    user_id: UUID
    endpoint: str
    endpoint_hash: str
    p256dh: str
    auth_ciphertext: bytes
    key_id: str
    created_at: datetime


class NotificationRepositoryPort(ABC):
    """In-app notifications of the session user, under row level security."""

    @abstractmethod
    def list_for_user(
        self, user_id: UUID, *, unread_only: bool, page: PageRequest
    ) -> Page[NotificationView]:
        """A page of the user's notifications, oldest first."""

    @abstractmethod
    def find_for_user(
        self, notification_id: UUID, user_id: UUID
    ) -> NotificationView | None:
        """The notification if it is the user's; ``None`` for anything else."""

    @abstractmethod
    def mark_read(self, notification_id: UUID, *, at: datetime) -> None:
        """Set ``read_at`` if it is still empty; a read notification keeps its time."""


class InAppStorePort(ABC):
    """Writes an in-app notification and its delivery (SYSTEM context only)."""

    @abstractmethod
    def store(
        self,
        *,
        notification_id: UUID,
        delivery_id: UUID,
        clinic_id: UUID,
        recipient_user_id: UUID,
        entry: InAppEntry,
        at: datetime,
    ) -> None:
        """Insert the notification row and its delivery row as ``SENT``."""


class NotificationPreferencesPort(ABC):
    """The preferences of one person."""

    @abstractmethod
    def get(self, user_id: UUID) -> NotificationPreferences | None:
        """The stored preferences, or ``None`` if the person never chose any."""

    @abstractmethod
    def save(self, preferences: NotificationPreferences) -> None:
        """Insert or replace the preferences of the person."""


class PushSubscriptionPort(ABC):
    """Web Push subscriptions of one person."""

    @abstractmethod
    def replace_for_user(self, record: PushSubscriptionRecord) -> None:
        """Remove the person's subscriptions and store ``record`` in their place."""

    @abstractmethod
    def delete_for_user(self, user_id: UUID) -> None:
        """Remove every subscription of the person."""
