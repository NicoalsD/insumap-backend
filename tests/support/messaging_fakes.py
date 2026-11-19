"""In-memory doubles of the messaging and follow-up ports, and one clinic's world.

The gates are the real ones (``AssignedPatientGate``, ``OwnPatientGate``) over
the doubles below, so the access rules of the tests are the production rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataResource,
    PatientDirectoryPort,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.care_team.ports import CareTeamRepositoryPort
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.follow_ups.ports import FollowUpRepositoryPort
from insumap.application.messaging.ports import (
    MessageThreadRepositoryPort,
    ThreadMessageRepositoryPort,
    ThreadReadRepositoryPort,
)
from insumap.domain.access.policy import PatientRef
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.follow_ups.follow_up import FollowUp, FollowUpStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.messaging.message import MessageThread, ThreadMessage
from insumap.infrastructure.messaging_adapters import MessagingAdapters

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC = UUID(int=0xC1)
PATIENT = UUID(int=0xA1)
PATIENT_USER = UUID(int=0xB1)
DOCTOR = UUID(int=0xD0)
OTHER_DOCTOR = UUID(int=0xD1)
OTHER_PATIENT = UUID(int=0xA2)
ADMIN = UUID(int=0xAD)

PATIENT_RIGHTS = frozenset(
    {PermissionCode.MESSAGES_USE_OWN, PermissionCode.FOLLOW_UPS_READ_OWN}
)
DOCTOR_RIGHTS = frozenset(
    {PermissionCode.MESSAGES_USE_ASSIGNED, PermissionCode.FOLLOW_UPS_MANAGE}
)


def patient_actor() -> Actor:
    return Actor(
        user_id=PATIENT_USER,
        clinic_id=CLINIC,
        role=Role.PATIENT,
        permissions=PATIENT_RIGHTS,
        patient_id=PATIENT,
        mfa_verified=False,
    )


def doctor_actor(user_id: UUID = DOCTOR) -> Actor:
    return Actor(
        user_id=user_id,
        clinic_id=CLINIC,
        role=Role.DOCTOR,
        permissions=DOCTOR_RIGHTS,
        requires_mfa=True,
        mfa_verified=True,
    )


def admin_actor() -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=CLINIC,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset({PermissionCode.CARE_TEAM_READ}),
        requires_mfa=True,
        mfa_verified=True,
    )


def assignment(doctor: UUID = DOCTOR, *, patient: UUID = PATIENT) -> CareAssignment:
    return CareAssignment(
        assignment_id=UUID(int=0x700 + doctor.int),
        clinic_id=CLINIC,
        patient_id=patient,
        doctor_user_id=doctor,
        is_primary=True,
        assigned_by=ADMIN,
        assigned_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


class FakeThreads(MessageThreadRepositoryPort):
    def __init__(self) -> None:
        self.by_patient: dict[UUID, MessageThread] = {}

    @override
    def find_by_patient(self, patient_id: UUID) -> MessageThread | None:
        return self.by_patient.get(patient_id)

    @override
    def ensure(
        self, *, thread_id: UUID, clinic_id: UUID, patient_id: UUID
    ) -> MessageThread:
        if patient_id not in self.by_patient:
            self.by_patient[patient_id] = MessageThread(
                thread_id=thread_id, clinic_id=clinic_id, patient_id=patient_id
            )
        return self.by_patient[patient_id]

    @override
    def touch(self, thread_id: UUID, *, at: datetime) -> None:
        for patient_id, thread in self.by_patient.items():
            if thread.thread_id == thread_id:
                self.by_patient[patient_id] = MessageThread(
                    thread_id=thread.thread_id,
                    clinic_id=thread.clinic_id,
                    patient_id=thread.patient_id,
                    last_message_at=at,
                )


class FakeMessages(ThreadMessageRepositoryPort):
    def __init__(self) -> None:
        self.rows: list[ThreadMessage] = []

    @override
    def append(self, message: ThreadMessage) -> None:
        self.rows.append(message)

    @override
    def list_for_thread(
        self, thread_id: UUID, page: PageRequest
    ) -> Page[ThreadMessage]:
        rows = sorted(
            (m for m in self.rows if m.thread_id == thread_id),
            key=lambda m: m.message_id,
            reverse=True,
        )
        if page.after is not None:
            rows = [m for m in rows if m.message_id < page.after]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda m: m.message_id
        )


class FakeReadMarks(ThreadReadRepositoryPort):
    def __init__(self) -> None:
        self.marks: dict[tuple[UUID, UUID], datetime] = {}

    @override
    def mark_read(
        self, *, thread_id: UUID, user_id: UUID, clinic_id: UUID, at: datetime
    ) -> None:
        del clinic_id
        self.marks[(thread_id, user_id)] = at


class FakePatients(PatientDirectoryPort):
    def __init__(self) -> None:
        self.patients: dict[UUID, PatientRef] = {
            PATIENT: PatientRef(
                patient_id=PATIENT, clinic_id=CLINIC, user_id=PATIENT_USER
            ),
            OTHER_PATIENT: PatientRef(
                patient_id=OTHER_PATIENT, clinic_id=CLINIC, user_id=None
            ),
        }

    @override
    def find(self, patient_id: UUID) -> PatientRef | None:
        return self.patients.get(patient_id)


class FakeAssignedRecords(PatientRecordPort):
    """The access chain of the tests: assigned pairs pass, the rest is ``404``."""

    def __init__(self, *pairs: tuple[UUID, UUID]) -> None:
        self.assigned: set[tuple[UUID, UUID]] = set(pairs)
        self.reads: list[tuple[UUID, UUID, DataResource]] = []

    @override
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
    ) -> PatientRecord:
        del purpose
        self.reads.append((actor.user_id, patient_id, resource))
        if (actor.user_id, patient_id) not in self.assigned:
            raise ResourceNotFoundError
        return PatientRecord(patient_id=patient_id, clinic_id=CLINIC)


class FakeFollowUps(FollowUpRepositoryPort):
    def __init__(self) -> None:
        self.rows: dict[UUID, FollowUp] = {}

    @override
    def insert(self, follow_up: FollowUp) -> None:
        self.rows[follow_up.follow_up_id] = follow_up

    @override
    def get(self, follow_up_id: UUID) -> FollowUp | None:
        return self.rows.get(follow_up_id)

    @override
    def update(self, follow_up: FollowUp) -> None:
        self.rows[follow_up.follow_up_id] = follow_up

    @override
    def list_for_patient(
        self,
        patient_id: UUID,
        *,
        status: FollowUpStatus | None,
        page: PageRequest,
    ) -> Page[FollowUp]:
        rows = sorted(
            (
                f
                for f in self.rows.values()
                if f.patient_id == patient_id and (status is None or f.status is status)
            ),
            key=lambda f: f.follow_up_id,
            reverse=True,
        )
        if page.after is not None:
            rows = [f for f in rows if f.follow_up_id < page.after]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda f: f.follow_up_id
        )


class FakePatientAccounts(PatientDirectoryPort):
    """One patient with its account, whatever ids the caller of the app uses."""

    def __init__(self, *, patient_id: UUID, user_id: UUID, clinic_id: UUID) -> None:
        self._ref = PatientRef(
            patient_id=patient_id, clinic_id=clinic_id, user_id=user_id
        )

    @override
    def find(self, patient_id: UUID) -> PatientRef | None:
        return self._ref if patient_id == self._ref.patient_id else None


class MessagingWorld:
    """The messaging doubles of the API tests: the threads, reads and follow-ups."""

    def __init__(
        self,
        *,
        care_teams: CareTeamRepositoryPort,
        patient_id: UUID,
        patient_user: UUID,
        clinic_id: UUID,
    ) -> None:
        self.threads = FakeThreads()
        self.messages = FakeMessages()
        self.read_marks = FakeReadMarks()
        self.follow_ups = FakeFollowUps()
        self.patients = FakePatientAccounts(
            patient_id=patient_id, user_id=patient_user, clinic_id=clinic_id
        )
        self.care_teams = care_teams

    def adapters(self) -> MessagingAdapters:
        return MessagingAdapters(
            threads=self.threads,
            messages=self.messages,
            read_marks=self.read_marks,
            follow_ups=self.follow_ups,
            patients=self.patients,
            care_teams=self.care_teams,
        )
