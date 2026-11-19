"""The real subject of the access proxy: the record of a patient."""

from __future__ import annotations

from typing import final, override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataResource,
    PatientDirectoryPort,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.domain.common.errors import ResourceNotFoundError


@final
class PatientRecordRepository(PatientRecordPort):
    """Confirms the patient exists in the session clinic and returns its handle.

    It is the innermost piece of ``PhiAccessAuditDecorator(PatientRecordAccessProxy(
    PatientRecordRepository(...)))``. The readers of each clinical module build on
    the record it returns.
    """

    def __init__(self, patients: PatientDirectoryPort) -> None:
        self._patients = patients

    @override
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
    ) -> PatientRecord:
        del actor, purpose, resource
        patient = self._patients.find(patient_id)
        if patient is None:
            raise ResourceNotFoundError
        return PatientRecord(patient_id=patient.patient_id, clinic_id=patient.clinic_id)
