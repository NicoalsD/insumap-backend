"""Doubles of the access ports: a directory, a team, a subject and a log."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    CareTeamAssignmentPort,
    DataAccessLogPort,
    DataAccessRecord,
    DataResource,
    PatientDirectoryPort,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.domain.access.policy import PatientRef
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.identity.roles import Role

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC = UUID(int=9)
PATIENT = UUID(int=100)
PATIENT_USER = UUID(int=50)
DOCTOR = UUID(int=1)
OTHER_DOCTOR = UUID(int=2)
ADMIN = UUID(int=3)


def actor(user_id: UUID, role: Role) -> Actor:
    return Actor(
        user_id=user_id,
        clinic_id=CLINIC,
        role=role,
        patient_id=PATIENT if role is Role.PATIENT else None,
        requires_mfa=role is not Role.PATIENT,
        mfa_verified=True,
    )


def assignment(
    doctor: UUID = DOCTOR,
    *,
    patient: UUID = PATIENT,
    ended_at: datetime | None = None,
    is_primary: bool = True,
) -> CareAssignment:
    return CareAssignment(
        assignment_id=UUID(int=700 + doctor.int),
        clinic_id=CLINIC,
        patient_id=patient,
        doctor_user_id=doctor,
        is_primary=is_primary,
        assigned_by=ADMIN,
        assigned_at=datetime(2026, 11, 1, tzinfo=UTC),
        ended_at=ended_at,
    )


class FakeDirectory(PatientDirectoryPort):
    def __init__(self) -> None:
        self.patients = {
            PATIENT: PatientRef(
                patient_id=PATIENT, clinic_id=CLINIC, user_id=PATIENT_USER
            )
        }

    @override
    def find(self, patient_id: UUID) -> PatientRef | None:
        return self.patients.get(patient_id)


class FakeAssignments(CareTeamAssignmentPort):
    def __init__(self, *rows: CareAssignment) -> None:
        self.rows = list(rows)

    @override
    def for_patient(self, patient_id: UUID) -> Sequence[CareAssignment]:
        return [row for row in self.rows if row.patient_id == patient_id]


class RecordingSubject(PatientRecordPort):
    def __init__(self) -> None:
        self.calls = 0

    @override
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
    ) -> PatientRecord:
        self.calls += 1
        return PatientRecord(patient_id=patient_id, clinic_id=CLINIC)


class InMemoryDataAccessLog(DataAccessLogPort):
    def __init__(self) -> None:
        self.granted: list[DataAccessRecord] = []
        self.denied: list[DataAccessRecord] = []
        self.fail_granted = False

    @override
    def record_granted(self, record: DataAccessRecord) -> None:
        if self.fail_granted:
            raise RuntimeError("audit write failed")
        self.granted.append(record)

    @override
    def record_denied(self, record: DataAccessRecord) -> None:
        self.denied.append(record)
