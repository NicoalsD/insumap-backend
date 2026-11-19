"""``GET /notifications``: the in-app notifications of the caller, as text."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.ports import ConsentRepositoryPort
from insumap.application.notifications.gate import AccountNotificationGate
from insumap.application.notifications.ports import NotificationRepositoryPort
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.i18n import MessageCatalog


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationItem:
    """A notification with its text rendered from ``messages_es``."""

    notification_id: UUID
    notification_type: str
    title: str
    body: str
    entity_type: str | None
    entity_id: UUID | None
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ListNotificationsInput:
    """The caller, whether to show only unread ones, and the page asked for."""

    actor: Actor
    unread_only: bool
    page: PageRequest


@final
class ListNotificationsUseCase:
    """Lists the caller's own notifications; the repository adds the RLS scope."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        consents: ConsentRepositoryPort,
        notifications: NotificationRepositoryPort,
        messages: MessageCatalog,
    ) -> None:
        self._uow = uow
        self._gate = AccountNotificationGate(consents)
        self._notifications = notifications
        self._messages = messages

    def execute(self, input: ListNotificationsInput) -> Page[NotificationItem]:
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)):
            self._gate.enter(actor, PermissionCode.NOTIFICATIONS_READ_OWN)
            page = self._notifications.list_for_user(
                actor.user_id, unread_only=input.unread_only, page=input.page
            )
        return Page(
            items=[
                NotificationItem(
                    notification_id=row.notification_id,
                    notification_type=row.notification_type,
                    title=self._messages.render(f"{row.message_key}.title"),
                    body=self._messages.render(f"{row.message_key}.body"),
                    entity_type=row.entity_type,
                    entity_id=row.entity_id,
                    created_at=row.created_at,
                    read_at=row.read_at,
                )
                for row in page.items
            ],
            next_cursor=page.next_cursor,
        )
