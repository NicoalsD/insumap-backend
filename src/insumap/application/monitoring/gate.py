"""Who may touch which patient: the checks every records use case starts with."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessAction,
    DataResource,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.application.identity.ports import ConsentRepositoryPort
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class OwnScope:
    """The patient of the token and its clinic (V3: never from the request)."""

    actor: Actor
    clinic_id: UUID
    patient_id: UUID


@final
class OwnPatientGate:
    """Permission, rate limit, own patient and current consent (C3) of an endpoint.

    Call ``enter`` inside the transaction: the consent lookup runs under RLS.
    """

    def __init__(
        self, consents: ConsentRepositoryPort, rate_limit: RateLimitCheck | None = None
    ) -> None:
        self._consents = consents
        self._rate_limit = rate_limit

    def enter(self, actor: Actor, permission: PermissionCode) -> OwnScope:
        actor.require(permission)
        if self._rate_limit is not None:
            self._rate_limit.ensure(str(actor.user_id))
        patient_id = actor.own_patient_id()
        if actor.clinic_id is None:
            raise PermissionDeniedError
        if not self._consents.has_accepted_current(patient_id, actor.clinic_id):
            raise ConsentRequiredError
        return OwnScope(actor=actor, clinic_id=actor.clinic_id, patient_id=patient_id)


@final
class AssignedPatientGate:
    """Permission and the access proxy (P11) of a doctor endpoint.

    A patient who is not assigned, belongs to another clinic or does not exist
    answers the same ``404`` (decided by the ``PatientRecordPort`` chain).
    """

    def __init__(self, patients: PatientRecordPort) -> None:
        self._patients = patients

    def enter(
        self,
        actor: Actor,
        permission: PermissionCode,
        patient_id: UUID,
        resource: DataResource,
        action: DataAccessAction = DataAccessAction.READ,
    ) -> UUID:
        actor.require(permission)
        self._patients.read_record(
            actor, patient_id, AccessPurpose.CARE, resource, action
        )
        return patient_id
