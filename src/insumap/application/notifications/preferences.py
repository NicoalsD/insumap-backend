"""Preferences of the caller: the channels and the quiet hours (P07 settings)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import final

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.ports import ConsentRepositoryPort
from insumap.application.notifications.gate import AccountNotificationGate
from insumap.application.notifications.ports import NotificationPreferencesPort
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.notifications.preferences import (
    Channel,
    NotificationPreferences,
    QuietHours,
)
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateNotificationPreferencesInput:
    """Every channel and the silence window; ``quiet_start`` ``None`` means none."""

    actor: Actor
    channels: dict[Channel, bool]
    quiet_start: time | None
    quiet_end: time | None


@final
class _PreferencesFor:
    """The preferences of the caller, or the defaults if none were ever saved."""

    def __init__(self, store: NotificationPreferencesPort) -> None:
        self._store = store

    def load(self, actor: Actor) -> NotificationPreferences:
        stored = self._store.get(actor.user_id)
        if stored is not None:
            return stored
        return NotificationPreferences.defaults(
            user_id=actor.user_id, clinic_id=actor.clinic_id
        )


@final
class GetNotificationPreferencesUseCase:
    """Reads the caller's preferences; nothing is written by a read."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        consents: ConsentRepositoryPort,
        store: NotificationPreferencesPort,
    ) -> None:
        self._uow = uow
        self._gate = AccountNotificationGate(consents)
        self._preferences = _PreferencesFor(store)

    def execute(self, actor: Actor) -> NotificationPreferences:
        with self._uow.begin(TransactionContext.for_actor(actor)):
            self._gate.enter(actor, PermissionCode.NOTIFICATION_PREFERENCES_MANAGE_OWN)
            return self._preferences.load(actor)


@final
class UpdateNotificationPreferencesUseCase:
    """Replaces the channels and the silence window of the caller."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        consents: ConsentRepositoryPort,
        store: NotificationPreferencesPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = AccountNotificationGate(consents)
        self._store = store
        self._preferences = _PreferencesFor(store)
        self._clock = clock

    def execute(
        self, input: UpdateNotificationPreferencesInput
    ) -> NotificationPreferences:
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._gate.enter(actor, PermissionCode.NOTIFICATION_PREFERENCES_MANAGE_OWN)
            quiet = (
                None
                if input.quiet_start is None or input.quiet_end is None
                else QuietHours(start=input.quiet_start, end=input.quiet_end)
            )
            updated = self._preferences.load(actor).updated(
                channels=input.channels, quiet_hours=quiet, at=self._clock.now()
            )
            self._store.save(updated)
            unit.commit()
        return updated
