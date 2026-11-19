"""Pattern: P18 State. ``ClinicState``: ``ACTIVE <-> SUSPENDED``."""

import pytest

from insumap.domain.clinic.clinic import (
    ActiveClinicState,
    ClinicState,
    ClinicStatus,
    SuspendedClinicState,
)
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.shared.errors import ErrorCode


@pytest.mark.parametrize(
    ("status", "state_type"),
    [
        (ClinicStatus.ACTIVE, ActiveClinicState),
        (ClinicStatus.SUSPENDED, SuspendedClinicState),
    ],
)
def test_a_persisted_status_rebuilds_its_state(
    status: ClinicStatus, state_type: type[ClinicState]
) -> None:
    state = ClinicState.from_status(status)

    assert isinstance(state, state_type)
    assert state.status is status


def test_an_active_clinic_can_be_suspended_but_not_reactivated() -> None:
    state = ActiveClinicState()

    assert state.suspend().status is ClinicStatus.SUSPENDED
    with pytest.raises(InvalidStateTransitionError) as error:
        state.reactivate()
    assert error.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert error.value.detail == {
        "machine": "clinic",
        "status": "ACTIVE",
        "action": "reactivate",
    }


def test_a_suspended_clinic_can_be_reactivated_but_not_suspended_again() -> None:
    state = SuspendedClinicState()

    assert state.reactivate().status is ClinicStatus.ACTIVE
    with pytest.raises(InvalidStateTransitionError):
        state.suspend()


def test_the_cycle_can_repeat() -> None:
    state: ClinicState = ActiveClinicState()

    for _ in range(3):
        state = state.suspend().reactivate()

    assert state.status is ClinicStatus.ACTIVE
