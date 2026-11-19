from datetime import timedelta
from uuid import UUID

import pytest

from insumap.domain.access.policy import AccessDecision, PatientAccessPolicy, PatientRef
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.identity.roles import Role
from tests.support.access_fakes import (
    ADMIN,
    CLINIC,
    DOCTOR,
    NOW,
    OTHER_DOCTOR,
    PATIENT,
    PATIENT_USER,
    assignment,
)

POLICY = PatientAccessPolicy()
REF = PatientRef(patient_id=PATIENT, clinic_id=CLINIC, user_id=PATIENT_USER)


def decide(
    user_id: UUID,
    role: Role,
    *rows: CareAssignment,
    patient: PatientRef = REF,
) -> AccessDecision:
    return POLICY.decide(
        user_id=user_id,
        role=role,
        patient=patient,
        assignments=list(rows),
        at=NOW,
    )


def test_the_patient_is_granted_only_their_own_record() -> None:
    assert decide(PATIENT_USER, Role.PATIENT) is AccessDecision.GRANTED
    assert decide(UUID(int=51), Role.PATIENT) is AccessDecision.NOT_FOUND


def test_a_patient_without_an_account_is_never_granted() -> None:
    orphan = PatientRef(patient_id=PATIENT, clinic_id=CLINIC, user_id=None)

    assert (
        decide(PATIENT_USER, Role.PATIENT, patient=orphan) is AccessDecision.NOT_FOUND
    )


def test_a_doctor_needs_an_active_assignment_to_that_patient() -> None:
    assert decide(DOCTOR, Role.DOCTOR, assignment()) is AccessDecision.GRANTED
    assert decide(OTHER_DOCTOR, Role.DOCTOR, assignment()) is AccessDecision.NOT_FOUND
    assert decide(DOCTOR, Role.DOCTOR) is AccessDecision.NOT_FOUND


def test_an_assignment_to_another_patient_gives_nothing() -> None:
    other = assignment(patient=UUID(int=101))

    assert decide(DOCTOR, Role.DOCTOR, other) is AccessDecision.NOT_FOUND


def test_an_ended_assignment_gives_nothing_but_a_future_end_still_does() -> None:
    ended = assignment(ended_at=NOW - timedelta(seconds=1))
    ending = assignment(ended_at=NOW + timedelta(seconds=1))

    assert decide(DOCTOR, Role.DOCTOR, ended) is AccessDecision.NOT_FOUND
    assert decide(DOCTOR, Role.DOCTOR, ending) is AccessDecision.GRANTED


@pytest.mark.parametrize("role", [Role.CLINIC_ADMIN, Role.PLATFORM_ADMIN])
def test_administrators_are_forbidden_even_with_an_assignment(role: Role) -> None:
    assert decide(ADMIN, role, assignment(ADMIN)) is AccessDecision.FORBIDDEN
