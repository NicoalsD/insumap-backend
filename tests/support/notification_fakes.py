"""In-memory doubles of the notification ports, with the rules the rows keep."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import override
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.notifications.notification import (
    InAppEntry,
    NotificationChannel,
)
from insumap.application.notifications.ports import (
    InAppStorePort,
    NotificationPreferencesPort,
    NotificationRepositoryPort,
    NotificationView,
    PushSubscriptionPort,
    PushSubscriptionRecord,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.notifications.preferences import NotificationPreferences
from insumap.infrastructure.notification_adapters import NotificationAdapters
from insumap.infrastructure.notifications.web_push_channel import LoggingWebPushChannel
from tests.support.notifications import InMemoryChannel


class InMemoryNotificationStore(NotificationRepositoryPort, InAppStorePort):
    """In-app rows keyed by id; the recipient is kept beside each view."""

    def __init__(self) -> None:
        self.rows: dict[UUID, NotificationView] = {}
        self.recipients: dict[UUID, UUID] = {}
        self.clinics: dict[UUID, UUID] = {}
        self.deliveries: list[tuple[UUID, UUID, str]] = []

    def add(self, view: NotificationView, *, recipient: UUID) -> None:
        self.rows[view.notification_id] = view
        self.recipients[view.notification_id] = recipient

    @override
    def list_for_user(
        self, user_id: UUID, *, unread_only: bool, page: PageRequest
    ) -> Page[NotificationView]:
        rows = sorted(
            (
                row
                for nid, row in self.rows.items()
                if self.recipients[nid] == user_id
                and (not unread_only or row.read_at is None)
                and (page.after is None or nid > page.after)
            ),
            key=lambda row: row.notification_id,
        )
        return build_page(rows, limit=page.limit, key=lambda row: row.notification_id)

    @override
    def find_for_user(
        self, notification_id: UUID, user_id: UUID
    ) -> NotificationView | None:
        if self.recipients.get(notification_id) != user_id:
            return None
        return self.rows.get(notification_id)

    @override
    def mark_read(self, notification_id: UUID, *, at: datetime) -> None:
        row = self.rows[notification_id]
        if row.read_at is None:
            self.rows[notification_id] = replace(row, read_at=at)

    @override
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
        self.add(
            NotificationView(
                notification_id=notification_id,
                notification_type=entry.notification_type,
                message_key=entry.message_key,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                created_at=at,
                read_at=None,
            ),
            recipient=recipient_user_id,
        )
        self.clinics[notification_id] = clinic_id
        self.deliveries.append((delivery_id, notification_id, "IN_APP"))


class InMemoryPreferences(NotificationPreferencesPort):
    def __init__(self) -> None:
        self.by_user: dict[UUID, NotificationPreferences] = {}

    @override
    def get(self, user_id: UUID) -> NotificationPreferences | None:
        return self.by_user.get(user_id)

    @override
    def save(self, preferences: NotificationPreferences) -> None:
        self.by_user[preferences.user_id] = preferences


class InMemoryPushSubscriptions(PushSubscriptionPort):
    """One subscription per user; an endpoint in ``taken`` is someone else's."""

    def __init__(self) -> None:
        self.by_user: dict[UUID, PushSubscriptionRecord] = {}
        self.taken: set[str] = set()

    @override
    def replace_for_user(self, record: PushSubscriptionRecord) -> None:
        if record.endpoint_hash in self.taken:
            raise ConflictError("push_endpoint_registered")
        self.by_user[record.user_id] = record

    @override
    def delete_for_user(self, user_id: UUID) -> None:
        self.by_user.pop(user_id, None)


def notification_adapters(
    *,
    store: InMemoryNotificationStore | None = None,
    preferences: InMemoryPreferences | None = None,
    subscriptions: InMemoryPushSubscriptions | None = None,
    in_app: InMemoryChannel | None = None,
    web_push: NotificationChannel | None = None,
) -> NotificationAdapters:
    """The notification ports as doubles; the Web Push sender only logs by default."""
    store = store or InMemoryNotificationStore()
    return NotificationAdapters(
        notifications=store,
        in_app_store=store,
        preferences=preferences or InMemoryPreferences(),
        push_subscriptions=subscriptions or InMemoryPushSubscriptions(),
        in_app=in_app or InMemoryChannel(external=False),
        web_push=web_push or LoggingWebPushChannel(),
    )
