"""Own-patient gate of the consent routes: exempt from the consent check (C3)."""

from __future__ import annotations

from typing import final

from insumap.application.common.actor import Actor
from insumap.application.monitoring.gate import OwnScope
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode


@final
class OwnConsentGate:
    """Permission and own patient of a consent route, without the consent check.

    API.md 2.4, point 6: a patient with a version to accept must be able to
    accept it, so ``consents/*`` never asks for a current consent.
    """

    def enter(self, actor: Actor, permission: PermissionCode) -> OwnScope:
        actor.require(permission)
        patient_id = actor.own_patient_id()
        if actor.clinic_id is None:
            raise PermissionDeniedError
        return OwnScope(actor=actor, clinic_id=actor.clinic_id, patient_id=patient_id)
