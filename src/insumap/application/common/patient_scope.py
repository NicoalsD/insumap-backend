"""Which patient a messaging or follow-up call may reach (P11).

A doctor names the patient and must hold an assignment: the audited access
chain answers ``404`` for anyone else. A patient always works on its own record,
so a patient id in the request is refused: the id comes from the token (V3).
"""

from __future__ import annotations

from typing import Final, final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.common.actor import Actor
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.domain.common.text import invalid_field
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role

PATIENT_FIELD: Final = "patient_id"
REQUIRED: Final = "required"
NOT_ALLOWED: Final = "not_allowed"


@final
class PatientScope:
    """The patient a doctor names (assigned) or the patient of the token.

    Call ``enter`` inside the transaction: the gates read under row level security
    and the audit row of an assigned read joins that transaction.

    Pattern: P11 Proxy (uses the access gates)
    """

    def __init__(self, *, assigned: AssignedPatientGate, own: OwnPatientGate) -> None:
        self._assigned = assigned
        self._own = own

    def enter(
        self,
        actor: Actor,
        patient_id: UUID | None,
        *,
        staff_permission: PermissionCode,
        own_permission: PermissionCode,
        resource: DataResource,
    ) -> UUID:
        """The patient the call works on; a ``403``, ``404`` or ``422`` otherwise."""
        if actor.role is Role.DOCTOR:
            if patient_id is None:
                raise invalid_field(PATIENT_FIELD, REQUIRED)
            return self._assigned.enter(actor, staff_permission, patient_id, resource)
        if actor.role is Role.PATIENT:
            if patient_id is not None:
                raise invalid_field(PATIENT_FIELD, NOT_ALLOWED)
            return self._own.enter(actor, own_permission).patient_id
        raise PermissionDeniedError
