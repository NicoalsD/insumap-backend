"""Protection proxy of the clinical record (P11)."""

from __future__ import annotations

from typing import final, override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    CareTeamAssignmentPort,
    DataResource,
    PatientDirectoryPort,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.domain.access.policy import AccessDecision, PatientAccessPolicy
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.shared.time import Clock


@final
class PatientRecordAccessProxy(PatientRecordPort):
    """Protection proxy: only the assigned care team, the patient or nobody else.

    It has the same interface as the real subject and the container hands out
    only the proxy, so a use case cannot skip the check. A doctor who is not
    assigned, or whose assignment ended, and a patient reading another record
    get ``404``; an administrator gets ``403``. A patient of another clinic is
    invisible to row level security: ``404`` too. The subject is never called
    when the access is denied.

    Pattern: P11 Proxy
    """

    def __init__(
        self,
        subject: PatientRecordPort,
        patients: PatientDirectoryPort,
        assignments: CareTeamAssignmentPort,
        policy: PatientAccessPolicy,
        clock: Clock,
    ) -> None:
        self._subject = subject
        self._patients = patients
        self._assignments = assignments
        self._policy = policy
        self._clock = clock

    @override
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
    ) -> PatientRecord:
        patient = self._patients.find(patient_id)
        if patient is None:
            raise ResourceNotFoundError
        decision = self._policy.decide(
            user_id=actor.user_id,
            role=actor.role,
            patient=patient,
            assignments=self._assignments.for_patient(patient_id),
            at=self._clock.now(),
        )
        if decision is AccessDecision.FORBIDDEN:
            raise PermissionDeniedError
        if decision is AccessDecision.NOT_FOUND:
            raise ResourceNotFoundError
        return self._subject.read_record(actor, patient_id, purpose, resource)
