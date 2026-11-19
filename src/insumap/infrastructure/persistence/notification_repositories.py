"""Repositories of the notification tables: in-app rows, preferences and subscriptions.

Every statement runs in the session of the open transaction, so row level
security applies: a person sees and changes only their own rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.notifications.notification import InAppEntry
from insumap.application.notifications.ports import (
    InAppStorePort,
    NotificationPreferencesPort,
    NotificationRepositoryPort,
    NotificationView,
    PushSubscriptionPort,
    PushSubscriptionRecord,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.notifications.preferences import (
    Channel,
    NotificationPreferences,
    QuietHours,
)
from insumap.infrastructure.persistence.notifications_orm import (
    NotificationDeliveryOrm,
    NotificationOrm,
    NotificationPreferenceOrm,
    PushSubscriptionOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

IN_APP_CHANNEL: str = Channel.IN_APP.value
SENT: str = "SENT"
FIRST_ATTEMPT: int = 1
ENDPOINT_REGISTERED: str = "push_endpoint_registered"


def _view(row: NotificationOrm) -> NotificationView:
    return NotificationView(
        notification_id=row.id,
        notification_type=row.notification_type,
        message_key=row.message_key,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        created_at=row.created_at,
        read_at=row.read_at,
    )


@final
class NotificationRepository(NotificationRepositoryPort, InAppStorePort):
    """In-app notifications; the store runs only in the SYSTEM context (RLS)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def list_for_user(
        self, user_id: UUID, *, unread_only: bool, page: PageRequest
    ) -> Page[NotificationView]:
        statement = select(NotificationOrm).where(
            NotificationOrm.recipient_user_id == user_id
        )
        if unread_only:
            statement = statement.where(NotificationOrm.read_at.is_(None))
        if page.after is not None:
            statement = statement.where(NotificationOrm.id > page.after)
        rows = self._current.get().scalars(
            statement.order_by(NotificationOrm.id).limit(page.limit + 1)
        )
        cut = build_page(list(rows), limit=page.limit, key=lambda row: row.id)
        return Page(
            items=[_view(row) for row in cut.items], next_cursor=cut.next_cursor
        )

    @override
    def find_for_user(
        self, notification_id: UUID, user_id: UUID
    ) -> NotificationView | None:
        row = self._current.get().get(NotificationOrm, notification_id)
        if row is None or row.recipient_user_id != user_id:
            return None
        return _view(row)

    @override
    def mark_read(self, notification_id: UUID, *, at: datetime) -> None:
        row = self._current.get().get(NotificationOrm, notification_id)
        if row is not None and row.read_at is None:
            row.read_at = at

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
        session = self._current.get()
        session.add(
            NotificationOrm(
                id=notification_id,
                clinic_id=clinic_id,
                recipient_user_id=recipient_user_id,
                notification_type=entry.notification_type,
                message_key=entry.message_key,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                alert_id=entry.alert_id,
                # Explicit so the insert has no RETURNING: the SYSTEM context may not
                # read its own notification back (the select policy is per recipient).
                params={},
                created_at=at,
            )
        )
        # The ORM declares no relationship between the two rows, so the notification
        # is flushed before its delivery references it (foreign key order).
        session.flush()
        session.add(
            NotificationDeliveryOrm(
                id=delivery_id,
                clinic_id=clinic_id,
                notification_id=notification_id,
                channel=IN_APP_CHANNEL,
                status=SENT,
                attempts=FIRST_ATTEMPT,
                sent_at=at,
                created_at=at,
                updated_at=at,
            )
        )
        session.flush()


@final
class NotificationPreferencesRepository(NotificationPreferencesPort):
    """One preferences row per person (``alerts.notification_preferences``)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, user_id: UUID) -> NotificationPreferences | None:
        row = self._current.get().get(NotificationPreferenceOrm, user_id)
        if row is None:
            return None
        enabled = {
            Channel.EMAIL: row.email_enabled,
            Channel.WEB_PUSH: row.web_push_enabled,
            Channel.IN_APP: row.in_app_enabled,
        }
        quiet = (
            None
            if row.quiet_start is None or row.quiet_end is None
            else QuietHours(start=row.quiet_start, end=row.quiet_end)
        )
        return NotificationPreferences(
            user_id=row.user_id,
            clinic_id=row.clinic_id,
            enabled=frozenset(channel for channel, on in enabled.items() if on),
            quiet_hours=quiet,
            updated_at=row.updated_at,
        )

    @override
    def save(self, preferences: NotificationPreferences) -> None:
        session = self._current.get()
        row = session.get(NotificationPreferenceOrm, preferences.user_id)
        if row is None:
            row = NotificationPreferenceOrm(
                user_id=preferences.user_id, clinic_id=preferences.clinic_id
            )
            session.add(row)
        row.email_enabled = preferences.is_enabled(Channel.EMAIL)
        row.web_push_enabled = preferences.is_enabled(Channel.WEB_PUSH)
        row.in_app_enabled = preferences.is_enabled(Channel.IN_APP)
        row.quiet_start = (
            None if preferences.quiet_hours is None else preferences.quiet_hours.start
        )
        row.quiet_end = (
            None if preferences.quiet_hours is None else preferences.quiet_hours.end
        )
        if preferences.updated_at is not None:
            row.updated_at = preferences.updated_at
        session.flush()


@final
class PushSubscriptionRepository(PushSubscriptionPort):
    """Web Push subscriptions; the endpoint hash is unique across all users."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def replace_for_user(self, record: PushSubscriptionRecord) -> None:
        session = self._current.get()
        session.execute(
            delete(PushSubscriptionOrm).where(
                PushSubscriptionOrm.user_id == record.user_id
            )
        )
        session.add(
            PushSubscriptionOrm(
                id=record.subscription_id,
                clinic_id=record.clinic_id,
                user_id=record.user_id,
                endpoint=record.endpoint,
                endpoint_hash=record.endpoint_hash,
                p256dh=record.p256dh,
                auth_ciphertext=record.auth_ciphertext,
                key_id=record.key_id,
                is_active=True,
                created_at=record.created_at,
            )
        )
        try:
            session.flush()
        except IntegrityError:
            # Another person's row holds this endpoint and row level security hides
            # it, so the conflict is reported without naming the other account.
            raise ConflictError(ENDPOINT_REGISTERED) from None

    @override
    def delete_for_user(self, user_id: UUID) -> None:
        self._current.get().execute(
            delete(PushSubscriptionOrm).where(PushSubscriptionOrm.user_id == user_id)
        )
