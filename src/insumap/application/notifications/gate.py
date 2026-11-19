"""Who may read or change their own notification settings: permission and consent."""

from __future__ import annotations

from typing import final

from insumap.application.common.actor import Actor
from insumap.application.identity.ports import ConsentRepositoryPort
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role


@final
class AccountNotificationGate:
    """Permission for every role; the current consent (C3) for a patient only.

    Staff reach these routes after the second factor, which the session actor
    already checked (C2). Call ``enter`` inside the transaction: the consent
    lookup runs under row level security.
    """

    def __init__(self, consents: ConsentRepositoryPort) -> None:
        self._consents = consents

    def enter(self, actor: Actor, permission: PermissionCode) -> None:
        actor.require(permission)
        if actor.role is not Role.PATIENT:
            return
        if actor.clinic_id is None:
            raise PermissionDeniedError
        patient_id = actor.own_patient_id()
        if not self._consents.has_accepted_current(patient_id, actor.clinic_id):
            raise ConsentRequiredError
