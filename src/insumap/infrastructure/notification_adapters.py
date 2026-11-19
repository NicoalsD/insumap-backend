"""The adapters behind the notification ports, built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import UnitOfWorkPort
from insumap.application.notifications.notification import NotificationChannel
from insumap.application.notifications.ports import (
    InAppStorePort,
    NotificationPreferencesPort,
    NotificationRepositoryPort,
    PushSubscriptionPort,
)
from insumap.infrastructure.notifications.in_app_channel import InAppNotificationChannel
from insumap.infrastructure.notifications.web_push_channel import LoggingWebPushChannel
from insumap.infrastructure.persistence.notification_repositories import (
    NotificationPreferencesRepository,
    NotificationRepository,
    PushSubscriptionRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationAdapters:
    """Ports of the notification slice, wired by ``Container``.

    ``in_app`` and ``web_push`` are the channels of the P07 bridge; the
    repositories back the use cases. Tests pass their own doubles; production
    gets ``build_notification_adapters``.
    """

    notifications: NotificationRepositoryPort
    in_app_store: InAppStorePort
    preferences: NotificationPreferencesPort
    push_subscriptions: PushSubscriptionPort
    in_app: NotificationChannel
    web_push: NotificationChannel


def build_notification_adapters(
    *,
    current: CurrentSession,
    unit_of_work: UnitOfWorkPort,
    ids: IdGenerator,
    clock: Clock,
) -> NotificationAdapters:
    """Production adapters: PostgreSQL rows and the logging Web Push channel."""
    notifications = NotificationRepository(current)
    return NotificationAdapters(
        notifications=notifications,
        in_app_store=notifications,
        preferences=NotificationPreferencesRepository(current),
        push_subscriptions=PushSubscriptionRepository(current),
        in_app=InAppNotificationChannel(
            uow=unit_of_work, store=notifications, ids=ids, clock=clock
        ),
        web_push=LoggingWebPushChannel(),
    )
