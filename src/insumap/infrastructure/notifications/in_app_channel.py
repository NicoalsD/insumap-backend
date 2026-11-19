"""The in-app channel: stores the notification and its delivery as ``SENT``.

Pattern: P07 Bridge (implementor)

It runs after the commit of the transaction that announced the event, so it
opens its own unit of work in the SYSTEM context. Row level security lets only
that context insert notifications; a person cannot write one for themselves.
"""

from __future__ import annotations

import logging
from typing import final, override
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.notifications.notification import (
    ChannelNotSupportedError,
    InAppEntry,
    NotificationChannel,
    Recipient,
)
from insumap.application.notifications.ports import InAppStorePort
from insumap.domain.identity.roles import Role
from insumap.shared.time import Clock

logger = logging.getLogger(__name__)

IN_APP_KIND: str = "in_app"


@final
class InAppNotificationChannel(NotificationChannel):
    """Writes the notification where the person reads it inside the app.

    Pattern: P07 Bridge (implementor)
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        store: InAppStorePort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._store = store
        self._ids = ids
        self._clock = clock

    @property
    @override
    def is_external(self) -> bool:
        return False

    @override
    def deliver(
        self,
        *,
        recipient: Recipient,
        subject: str,
        body: str,
        entry: InAppEntry | None = None,
    ) -> None:
        # The text is rendered from the key when the person reads it: the
        # subject and the body are not stored.
        del subject, body
        clinic_id = recipient.clinic_id
        if entry is None or clinic_id is None:
            raise ChannelNotSupportedError(IN_APP_KIND)
        self._store_in_app(recipient.user_id, clinic_id, entry)
        logger.info(
            "In-app notification stored",
            extra={"recipient_id": str(recipient.user_id), "channel": IN_APP_KIND},
        )

    def _store_in_app(self, user_id: UUID, clinic_id: UUID, entry: InAppEntry) -> None:
        context = TransactionContext(clinic_id=clinic_id, role=Role.SYSTEM)
        with self._uow.begin(context) as unit:
            self._store.store(
                notification_id=self._ids.new_id(),
                delivery_id=self._ids.new_id(),
                clinic_id=clinic_id,
                recipient_user_id=user_id,
                entry=entry,
                at=self._clock.now(),
            )
            unit.commit()
