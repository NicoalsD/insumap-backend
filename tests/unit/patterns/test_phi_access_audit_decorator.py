"""Pattern: P09 Decorator. Every read of clinical data leaves a row."""

from uuid import UUID

import pytest

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessAction,
    DataAccessOutcome,
    DataResource,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.domain.access.policy import PatientAccessPolicy
from insumap.domain.identity.roles import Role
from insumap.infrastructure.access.access_proxy import PatientRecordAccessProxy
from insumap.infrastructure.access.audit_decorator import PhiAccessAuditDecorator
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.request_context import bind_request_id, unbind_request_id
from tests.support.access_fakes import (
    CLINIC,
    DOCTOR,
    NOW,
    OTHER_DOCTOR,
    PATIENT,
    FakeAssignments,
    FakeDirectory,
    InMemoryDataAccessLog,
    RecordingSubject,
    actor,
    assignment,
)
from tests.support.fixed_clock import FixedClock

RESOURCE = DataResource.GLUCOSE_READINGS


class BrokenSubject(PatientRecordPort):
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
        action: DataAccessAction = DataAccessAction.READ,
    ) -> PatientRecord:
        raise InsumapError(ErrorCode.INTERNAL_ERROR)


def chain(
    log: InMemoryDataAccessLog, subject: PatientRecordPort | None = None
) -> PhiAccessAuditDecorator:
    proxy = PatientRecordAccessProxy(
        subject or RecordingSubject(),
        FakeDirectory(),
        FakeAssignments(assignment()),
        PatientAccessPolicy(),
        FixedClock(NOW),
    )
    return PhiAccessAuditDecorator(proxy, log, FixedClock(NOW))


def test_a_granted_read_leaves_one_granted_row_without_clinical_data() -> None:
    log = InMemoryDataAccessLog()
    token = bind_request_id("req-9")
    try:
        chain(log).read_record(
            actor(DOCTOR, Role.DOCTOR), PATIENT, AccessPurpose.CARE, RESOURCE
        )
    finally:
        unbind_request_id(token)

    [row] = log.granted
    assert log.denied == []
    assert row.outcome is DataAccessOutcome.GRANTED
    assert (row.patient_id, row.actor_user_id, row.clinic_id) == (
        PATIENT,
        DOCTOR,
        CLINIC,
    )
    assert row.actor_role is Role.DOCTOR
    assert row.resource is RESOURCE
    assert row.purpose is AccessPurpose.CARE
    assert row.request_id == "req-9"
    assert row.occurred_at == NOW


@pytest.mark.parametrize(
    ("who", "role", "code"),
    [
        (OTHER_DOCTOR, Role.DOCTOR, ErrorCode.NOT_FOUND),
        (OTHER_DOCTOR, Role.CLINIC_ADMIN, ErrorCode.FORBIDDEN),
    ],
)
def test_a_denied_read_leaves_a_denied_row_and_the_same_error_propagates(
    who: UUID, role: Role, code: ErrorCode
) -> None:
    log = InMemoryDataAccessLog()

    with pytest.raises(InsumapError) as error:
        chain(log).read_record(
            actor(who, role),
            PATIENT,
            AccessPurpose.CARE,
            RESOURCE,
        )

    assert error.value.code is code
    assert log.granted == []
    [row] = log.denied
    assert row.outcome is DataAccessOutcome.DENIED


def test_if_the_audit_write_fails_the_read_fails() -> None:
    log = InMemoryDataAccessLog()
    log.fail_granted = True

    with pytest.raises(RuntimeError, match="audit write failed"):
        chain(log).read_record(
            actor(DOCTOR, Role.DOCTOR), PATIENT, AccessPurpose.CARE, RESOURCE
        )


def test_an_error_that_is_not_a_denial_leaves_no_denied_row() -> None:
    log = InMemoryDataAccessLog()

    with pytest.raises(InsumapError) as error:
        chain(log, BrokenSubject()).read_record(
            actor(DOCTOR, Role.DOCTOR), PATIENT, AccessPurpose.CARE, RESOURCE
        )

    assert error.value.code is ErrorCode.INTERNAL_ERROR
    assert log.denied == [] and log.granted == []


def test_an_export_is_recorded_with_the_export_action() -> None:
    log = InMemoryDataAccessLog()
    chain(log).read_record(
        actor(DOCTOR, Role.DOCTOR),
        PATIENT,
        AccessPurpose.CARE,
        DataResource.REPORT,
        DataAccessAction.EXPORT,
    )

    [row] = log.granted
    assert row.action is DataAccessAction.EXPORT
    assert row.resource is DataResource.REPORT


def test_a_plain_read_defaults_to_the_read_action() -> None:
    log = InMemoryDataAccessLog()
    chain(log).read_record(
        actor(DOCTOR, Role.DOCTOR), PATIENT, AccessPurpose.CARE, RESOURCE
    )

    assert [row.action for row in log.granted] == [DataAccessAction.READ]
