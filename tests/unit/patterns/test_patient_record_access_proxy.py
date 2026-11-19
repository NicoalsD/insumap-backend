"""Pattern: P11 Proxy. Only the assigned care team reaches the clinical record."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.access.ports import AccessPurpose, DataResource
from insumap.domain.access.policy import PatientAccessPolicy
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.identity.roles import Role
from insumap.infrastructure.access.access_proxy import PatientRecordAccessProxy
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.access_fakes import (
    ADMIN,
    DOCTOR,
    NOW,
    OTHER_DOCTOR,
    PATIENT,
    PATIENT_USER,
    FakeAssignments,
    FakeDirectory,
    RecordingSubject,
    actor,
    assignment,
)
from tests.support.fixed_clock import FixedClock

CARE = AccessPurpose.CARE
RESOURCE = DataResource.GLUCOSE_READINGS


def build(
    subject: RecordingSubject, *rows: CareAssignment, clock: FixedClock | None = None
) -> PatientRecordAccessProxy:
    return PatientRecordAccessProxy(
        subject,
        FakeDirectory(),
        FakeAssignments(*rows),
        PatientAccessPolicy(),
        clock or FixedClock(NOW),
    )


def code_of(error: pytest.ExceptionInfo[InsumapError]) -> ErrorCode:
    return error.value.code


def test_an_assigned_doctor_reaches_the_record_through_the_subject() -> None:
    subject = RecordingSubject()

    record = build(subject, assignment()).read_record(
        actor(DOCTOR, Role.DOCTOR), PATIENT, CARE, RESOURCE
    )

    assert record.patient_id == PATIENT
    assert subject.calls == 1


def test_an_unassigned_doctor_gets_not_found_and_the_subject_is_not_called() -> None:
    subject = RecordingSubject()

    with pytest.raises(InsumapError) as error:
        build(subject, assignment()).read_record(
            actor(OTHER_DOCTOR, Role.DOCTOR), PATIENT, CARE, RESOURCE
        )

    assert code_of(error) is ErrorCode.NOT_FOUND
    assert subject.calls == 0


def test_a_withdrawn_assignment_removes_the_access_when_it_ends() -> None:
    clock = FixedClock(NOW)
    proxy = build(
        RecordingSubject(), assignment(ended_at=NOW + timedelta(hours=1)), clock=clock
    )
    assert proxy.read_record(actor(DOCTOR, Role.DOCTOR), PATIENT, CARE, RESOURCE)

    clock.advance(timedelta(hours=2))

    with pytest.raises(InsumapError) as error:
        proxy.read_record(actor(DOCTOR, Role.DOCTOR), PATIENT, CARE, RESOURCE)
    assert code_of(error) is ErrorCode.NOT_FOUND


def test_a_missing_patient_and_an_unassigned_one_answer_identically() -> None:
    proxy = build(RecordingSubject(), assignment())
    unassigned = actor(OTHER_DOCTOR, Role.DOCTOR)

    with pytest.raises(InsumapError) as hidden:
        proxy.read_record(unassigned, PATIENT, CARE, RESOURCE)
    with pytest.raises(InsumapError) as missing:
        proxy.read_record(unassigned, UUID(int=404), CARE, RESOURCE)

    assert hidden.value.code is missing.value.code is ErrorCode.NOT_FOUND
    assert hidden.value.detail == missing.value.detail
    assert hidden.value.message_key == missing.value.message_key


@pytest.mark.parametrize("role", [Role.CLINIC_ADMIN, Role.PLATFORM_ADMIN])
def test_an_administrator_gets_forbidden(role: Role) -> None:
    subject = RecordingSubject()

    with pytest.raises(InsumapError) as error:
        build(subject, assignment()).read_record(
            actor(ADMIN, role), PATIENT, CARE, RESOURCE
        )

    assert code_of(error) is ErrorCode.FORBIDDEN
    assert subject.calls == 0


def test_the_patient_reads_their_own_record_and_nobody_elses() -> None:
    proxy = build(RecordingSubject())

    own = proxy.read_record(
        actor(PATIENT_USER, Role.PATIENT), PATIENT, AccessPurpose.SELF, RESOURCE
    )
    with pytest.raises(InsumapError) as error:
        proxy.read_record(
            actor(UUID(int=51), Role.PATIENT), PATIENT, AccessPurpose.SELF, RESOURCE
        )

    assert own.patient_id == PATIENT
    assert code_of(error) is ErrorCode.NOT_FOUND
