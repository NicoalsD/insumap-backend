from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.domain.care_team.assignment import (
    CareAssignment,
    CareTeam,
    CareTeamChange,
)
from insumap.domain.common.errors import ConflictError, ReasonRequiredError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import InvalidStateTransitionError

PATIENT = UUID(int=100)
CLINIC = UUID(int=9)
ADMIN = UUID(int=3)
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
REASON = Reason.parse("Cambio de turno de la médica")


def doctor(number: int) -> UUID:
    return UUID(int=1000 + number)


def member(number: int, *, primary: bool = False) -> CareAssignment:
    return CareAssignment(
        assignment_id=UUID(int=2000 + number),
        clinic_id=CLINIC,
        patient_id=PATIENT,
        doctor_user_id=doctor(number),
        is_primary=primary,
        assigned_by=ADMIN,
        assigned_at=datetime(2026, 11, 1, tzinfo=UTC),
    )


def team(*members: CareAssignment) -> CareTeam:
    return CareTeam(patient_id=PATIENT, open_assignments=members)


def assign(current: CareTeam, number: int, *, primary: bool = False) -> CareTeamChange:
    return current.assign(
        assignment_id=UUID(int=3000 + number),
        clinic_id=CLINIC,
        doctor_user_id=doctor(number),
        is_primary=primary,
        assigned_by=ADMIN,
        at=NOW,
    )


# Assign.


def test_the_first_doctor_of_a_team_is_the_primary_even_if_not_asked() -> None:
    change = assign(team(), 1, primary=False)

    [created] = change.added
    assert created.is_primary is True
    assert change.updated == ()


def test_a_later_doctor_is_not_primary_unless_asked() -> None:
    change = assign(team(member(1, primary=True)), 2)

    assert change.added[0].is_primary is False
    assert change.updated == ()


def test_a_new_primary_demotes_the_old_one_in_the_same_change() -> None:
    change = assign(team(member(1, primary=True)), 2, primary=True)

    assert [a.is_primary for a in change.updated] == [False]
    assert change.updated[0].doctor_user_id == doctor(1)
    assert change.added[0].is_primary is True


def test_the_same_doctor_cannot_be_assigned_twice() -> None:
    with pytest.raises(ConflictError):
        assign(team(member(1, primary=True)), 1)


# Make primary.


def test_make_primary_swaps_the_role_demoting_first() -> None:
    change = team(member(1, primary=True), member(2)).make_primary(UUID(int=2002))

    assert [(a.doctor_user_id, a.is_primary) for a in change.updated] == [
        (doctor(1), False),
        (doctor(2), True),
    ]


def test_make_primary_of_the_primary_changes_nothing_of_substance() -> None:
    change = team(member(1, primary=True)).make_primary(UUID(int=2001))

    assert [a.is_primary for a in change.updated] == [True]


def test_only_an_open_assignment_can_become_primary() -> None:
    with pytest.raises(InvalidStateTransitionError):
        team(member(1, primary=True)).make_primary(UUID(int=9999))


# Reassign.


def test_reassign_ends_the_old_assignment_and_the_new_doctor_inherits_the_role() -> (
    None
):
    change = team(member(1, primary=True), member(2)).reassign(
        assignment_id=UUID(int=2001),
        new_assignment_id=UUID(int=3003),
        new_doctor_user_id=doctor(3),
        by=ADMIN,
        at=NOW,
        reason=REASON,
    )

    [ended] = change.updated
    [created] = change.added
    assert ended.ended_at == NOW
    assert ended.ended_by == ADMIN
    assert ended.end_reason == REASON.text
    assert ended.is_primary is False
    assert (created.doctor_user_id, created.is_primary) == (doctor(3), True)
    assert created.assigned_at == NOW


def test_reassign_to_a_doctor_already_in_the_team_conflicts() -> None:
    with pytest.raises(ConflictError):
        team(member(1, primary=True), member(2)).reassign(
            assignment_id=UUID(int=2001),
            new_assignment_id=UUID(int=3002),
            new_doctor_user_id=doctor(2),
            by=ADMIN,
            at=NOW,
            reason=REASON,
        )


def test_reassign_of_an_ended_assignment_is_an_invalid_transition() -> None:
    with pytest.raises(InvalidStateTransitionError):
        team(member(1, primary=True)).reassign(
            assignment_id=UUID(int=9999),
            new_assignment_id=UUID(int=3002),
            new_doctor_user_id=doctor(2),
            by=ADMIN,
            at=NOW,
            reason=REASON,
        )


# End.


def test_ending_a_secondary_doctor_needs_no_replacement() -> None:
    change = team(member(1, primary=True), member(2)).end(
        assignment_id=UUID(int=2002),
        by=ADMIN,
        at=NOW,
        reason=REASON,
        new_primary_assignment_id=None,
    )

    [ended] = change.updated
    assert ended.doctor_user_id == doctor(2)
    assert ended.ended_at == NOW
    assert change.added == ()


def test_ending_the_primary_promotes_the_named_successor_after_ending_it() -> None:
    change = team(member(1, primary=True), member(2)).end(
        assignment_id=UUID(int=2001),
        by=ADMIN,
        at=NOW,
        reason=REASON,
        new_primary_assignment_id=UUID(int=2002),
    )

    assert [(a.doctor_user_id, a.is_primary) for a in change.updated] == [
        (doctor(1), False),
        (doctor(2), True),
    ]
    assert change.updated[0].ended_at == NOW


@pytest.mark.parametrize(
    "successor",
    [None, UUID(int=2001), UUID(int=9999)],
    ids=["none", "itself", "unknown"],
)
def test_ending_the_primary_without_a_valid_successor_conflicts(
    successor: UUID | None,
) -> None:
    with pytest.raises(ConflictError):
        team(member(1, primary=True), member(2)).end(
            assignment_id=UUID(int=2001),
            by=ADMIN,
            at=NOW,
            reason=REASON,
            new_primary_assignment_id=successor,
        )


def test_the_only_doctor_who_is_primary_cannot_be_withdrawn_without_replacement() -> (
    None
):
    with pytest.raises(ConflictError):
        team(member(1, primary=True)).end(
            assignment_id=UUID(int=2001),
            by=ADMIN,
            at=NOW,
            reason=REASON,
            new_primary_assignment_id=None,
        )


# Reason.


@pytest.mark.parametrize("raw", [None, "", "   ", "corto", "x" * 501])
def test_a_reason_outside_the_allowed_length_is_rejected(raw: str | None) -> None:
    with pytest.raises(ReasonRequiredError):
        Reason.parse(raw)


@pytest.mark.parametrize("raw", ["x" * 10, "  " + "y" * 500 + "  "])
def test_a_reason_at_the_limits_is_accepted_and_trimmed(raw: str) -> None:
    assert Reason.parse(raw).text == raw.strip()


def test_an_assignment_is_active_until_it_ends() -> None:
    open_one = member(1)
    ended = open_one.ended(by=ADMIN, at=NOW, reason=REASON)

    assert open_one.is_active(NOW) and open_one.is_open
    assert not ended.is_active(NOW)
    assert ended.is_active(datetime(2026, 11, 19, 11, 0, tzinfo=UTC))
