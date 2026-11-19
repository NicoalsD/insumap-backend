"""Patient account machine.

Pattern: P18 State
"""

import pytest

from insumap.domain.identity.account_state import (
    AccountStatus,
    PatientAccountState,
)
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.shared.errors import ErrorCode

ACTIONS = (
    "issue_credentials",
    "revoke_invitation",
    "activate",
    "suspend",
    "reactivate",
    "deactivate",
)
ALLOWED = {
    (AccountStatus.IMPORTED, "issue_credentials"): AccountStatus.INVITED,
    (AccountStatus.IMPORTED, "deactivate"): AccountStatus.DEACTIVATED,
    (AccountStatus.INVITED, "issue_credentials"): AccountStatus.INVITED,
    (AccountStatus.INVITED, "revoke_invitation"): AccountStatus.IMPORTED,
    (AccountStatus.INVITED, "activate"): AccountStatus.ACTIVE,
    (AccountStatus.INVITED, "deactivate"): AccountStatus.DEACTIVATED,
    (AccountStatus.ACTIVE, "suspend"): AccountStatus.SUSPENDED,
    (AccountStatus.ACTIVE, "deactivate"): AccountStatus.DEACTIVATED,
    (AccountStatus.SUSPENDED, "reactivate"): AccountStatus.ACTIVE,
    (AccountStatus.SUSPENDED, "deactivate"): AccountStatus.DEACTIVATED,
}


@pytest.mark.parametrize("status", list(AccountStatus))
def test_from_status_rebuilds_the_state_of_each_status(status: AccountStatus) -> None:
    assert PatientAccountState.from_status(status).status is status


@pytest.mark.parametrize(("status", "action"), list(ALLOWED))
def test_allowed_transitions_reach_the_documented_state(
    status: AccountStatus, action: str
) -> None:
    state = PatientAccountState.from_status(status)

    assert getattr(state, action)().status is ALLOWED[(status, action)]


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (status, action)
        for status in AccountStatus
        for action in ACTIONS
        if (status, action) not in ALLOWED
    ],
)
def test_every_other_transition_is_refused_with_409(
    status: AccountStatus, action: str
) -> None:
    state = PatientAccountState.from_status(status)

    with pytest.raises(InvalidStateTransitionError) as raised:
        getattr(state, action)()

    assert raised.value.code is ErrorCode.INVALID_STATE_TRANSITION
    assert raised.value.detail == {
        "machine": "patient_account",
        "status": status.value,
        "action": action,
    }


def test_only_an_active_account_can_sign_in() -> None:
    signing_in = {
        status
        for status in AccountStatus
        if PatientAccountState.from_status(status).can_sign_in
    }

    assert signing_in == {AccountStatus.ACTIVE}


def test_full_lifecycle_from_import_to_deactivation() -> None:
    state = PatientAccountState.from_status(AccountStatus.IMPORTED)

    state = state.issue_credentials().activate().suspend().reactivate().deactivate()

    assert state.status is AccountStatus.DEACTIVATED
