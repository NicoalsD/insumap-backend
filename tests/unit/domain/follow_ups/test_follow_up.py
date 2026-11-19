"""Follow-up controls (RF-86): scheduled in the future, closed once with a result."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.domain.common.reason import Reason
from insumap.domain.follow_ups.follow_up import (
    FollowUp,
    FollowUpOutcome,
    FollowUpStatus,
)
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.messaging_fakes import CLINIC, DOCTOR, NOW, PATIENT

NOTE = Reason.parse("Asistió y se revisó la rutina de insulina")


def _scheduled(days: int = 3) -> FollowUp:
    return FollowUp.schedule(
        follow_up_id=UUID(int=50),
        clinic_id=CLINIC,
        patient_id=PATIENT,
        scheduled_for=NOW + timedelta(days=days),
        by=DOCTOR,
        title="Control de seguimiento",
        at=NOW,
    )


def test_a_control_starts_scheduled_with_its_doctor() -> None:
    control = _scheduled()

    assert control.status is FollowUpStatus.SCHEDULED
    assert control.assigned_to == DOCTOR
    assert control.created_by == DOCTOR
    assert control.closed_at is None


def test_a_control_in_the_past_is_a_validation_error() -> None:
    with pytest.raises(InsumapError) as error:
        _scheduled(days=-1)

    assert error.value.code is ErrorCode.VALIDATION_ERROR


def test_closing_a_scheduled_control_records_outcome_and_note() -> None:
    closed = _scheduled().close(outcome=FollowUpOutcome.DONE, note=NOTE, at=NOW)

    assert closed.status is FollowUpStatus.DONE
    assert closed.result_note == NOTE.text
    assert closed.closed_at == NOW


def test_a_closed_control_never_closes_again() -> None:
    closed = _scheduled().close(outcome=FollowUpOutcome.MISSED, note=NOTE, at=NOW)

    with pytest.raises(InvalidStateTransitionError):
        closed.close(outcome=FollowUpOutcome.DONE, note=NOTE, at=NOW)
