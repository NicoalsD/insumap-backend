"""``POST /notifications/{notification_id}/read``: the caller reads a notification."""

from __future__ import annotations

from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.ports import ConsentRepositoryPort
from insumap.application.notifications.gate import AccountNotificationGate
from insumap.application.notifications.ports import NotificationRepositoryPort
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock


@final
class MarkNotificationReadUseCase:
    """Sets ``read_at`` once; a notification of another person is a ``404``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        consents: ConsentRepositoryPort,
        notifications: NotificationRepositoryPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = AccountNotificationGate(consents)
        self._notifications = notifications
        self._clock = clock

    def execute(self, actor: Actor, notification_id: UUID) -> None:
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._gate.enter(actor, PermissionCode.NOTIFICATIONS_READ_OWN)
            found = self._notifications.find_for_user(notification_id, actor.user_id)
            if found is None:
                raise ResourceNotFoundError
            if found.read_at is None:
                self._notifications.mark_read(notification_id, at=self._clock.now())
            unit.commit()
