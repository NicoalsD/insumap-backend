"""Web Push subscriptions of the caller: register the browser's endpoint, or remove it.

The endpoint and the keys come from the browser, so they are untrusted. The
auth secret is encrypted before it is stored (class S column).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.ports import ConsentRepositoryPort, SecretCipherPort
from insumap.application.notifications.gate import AccountNotificationGate
from insumap.application.notifications.ports import (
    PushSubscriptionPort,
    PushSubscriptionRecord,
)
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.notifications.errors import PushEndpointRejectedError
from insumap.domain.notifications.push import PushEndpoint
from insumap.shared.time import Clock

PUSH_BINDING: Final = "push_subscription"
"""Prefix of the associated data: the ciphertext only opens for this row."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterWebPushInput:
    actor: Actor
    endpoint: str
    p256dh: str
    auth: str


@final
class RegisterWebPushSubscriptionUseCase:
    """Stores the caller's subscription; a rejected endpoint is recorded and refused.

    A refused endpoint commits its security event before the ``422`` is raised,
    so the record survives the rollback that a raised error would cause.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        consents: ConsentRepositoryPort,
        subscriptions: PushSubscriptionPort,
        security_events: SecurityEventPort,
        cipher: SecretCipherPort,
        ids: IdGenerator,
        clock: Clock,
        allowed_hosts: tuple[str, ...],
    ) -> None:
        self._uow = uow
        self._gate = AccountNotificationGate(consents)
        self._subscriptions = subscriptions
        self._security_events = security_events
        self._cipher = cipher
        self._ids = ids
        self._clock = clock
        self._allowed_hosts = allowed_hosts

    def execute(self, input: RegisterWebPushInput) -> None:
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._gate.enter(actor, PermissionCode.NOTIFICATION_PREFERENCES_MANAGE_OWN)
            try:
                endpoint = PushEndpoint.parse(
                    input.endpoint, allowed_hosts=self._allowed_hosts
                )
            except PushEndpointRejectedError:
                self._security_events.record(
                    SecurityEvent(
                        event_type=SecurityEventType.PUSH_ENDPOINT_REJECTED,
                        user_id=actor.user_id,
                        clinic_id=actor.clinic_id,
                    )
                )
                unit.commit()
                raise
            endpoint_hash = endpoint.endpoint_hash
            sealed = self._cipher.encrypt(
                input.auth,
                associated_data=f"{PUSH_BINDING}:{actor.user_id}:{endpoint_hash}",
            )
            self._subscriptions.replace_for_user(
                PushSubscriptionRecord(
                    subscription_id=self._ids.new_id(),
                    clinic_id=actor.clinic_id,
                    user_id=actor.user_id,
                    endpoint=endpoint.url,
                    endpoint_hash=endpoint_hash,
                    p256dh=input.p256dh,
                    auth_ciphertext=sealed.ciphertext,
                    key_id=sealed.key_id,
                    created_at=self._clock.now(),
                )
            )
            unit.commit()


@final
class RemoveWebPushSubscriptionUseCase:
    """Removes every Web Push subscription of the caller."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        consents: ConsentRepositoryPort,
        subscriptions: PushSubscriptionPort,
    ) -> None:
        self._uow = uow
        self._gate = AccountNotificationGate(consents)
        self._subscriptions = subscriptions

    def execute(self, actor: Actor) -> None:
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._gate.enter(actor, PermissionCode.NOTIFICATION_PREFERENCES_MANAGE_OWN)
            self._subscriptions.delete_for_user(actor.user_id)
            unit.commit()
