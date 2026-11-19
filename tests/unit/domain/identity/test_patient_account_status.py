"""Patient account transitions on ``UserAccount`` (P18)."""

from dataclasses import replace
from uuid import UUID

import pytest

from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import ClinicSummary, UserAccount

REASON = "Suspensión por revisión administrativa"
CLINIC = ClinicSummary(
    clinic_id=UUID(int=3), name="Clínica de Prueba Demo", is_demo=True, is_active=True
)


def account(status: AccountStatus) -> UserAccount:
    return UserAccount(
        user_id=UUID(int=1),
        email=None,
        email_normalized=None,
        full_name="Paciente de Prueba Uno",
        password_hash=None,
        status=status,
        token_version=4,
        role=Role.PATIENT,
        requires_mfa=False,
        membership_active=True,
        clinic=CLINIC,
        patient_id=UUID(int=2),
        status_reason=None,
    )


def test_suspend_moves_an_active_account_and_keeps_the_reason() -> None:
    suspended = account(AccountStatus.ACTIVE).suspended(reason=REASON)

    assert suspended.status is AccountStatus.SUSPENDED
    assert suspended.status_reason == REASON
    assert suspended.can_sign_in is False


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.IMPORTED,
        AccountStatus.INVITED,
        AccountStatus.SUSPENDED,
        AccountStatus.DEACTIVATED,
    ],
)
def test_suspend_refuses_any_other_origin(status: AccountStatus) -> None:
    with pytest.raises(InvalidStateTransitionError):
        account(status).suspended(reason=REASON)


def test_reactivate_returns_a_suspended_account_to_active_and_clears_the_reason() -> (
    None
):
    suspended = replace(
        account(AccountStatus.SUSPENDED), status_reason=REASON, token_version=5
    )

    active = suspended.reactivated()

    assert active.status is AccountStatus.ACTIVE
    assert active.status_reason is None
    assert active.can_sign_in is True
    assert active.token_version == 5


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.IMPORTED,
        AccountStatus.INVITED,
        AccountStatus.ACTIVE,
        AccountStatus.DEACTIVATED,
    ],
)
def test_reactivate_refuses_any_other_origin(status: AccountStatus) -> None:
    with pytest.raises(InvalidStateTransitionError):
        account(status).reactivated()


@pytest.mark.parametrize(
    "status",
    [
        AccountStatus.IMPORTED,
        AccountStatus.INVITED,
        AccountStatus.ACTIVE,
        AccountStatus.SUSPENDED,
    ],
)
def test_deactivate_is_allowed_from_every_non_terminal_state(
    status: AccountStatus,
) -> None:
    closed = account(status).deactivated(reason=REASON)

    assert closed.status is AccountStatus.DEACTIVATED
    assert closed.status_reason == REASON


def test_deactivated_is_terminal() -> None:
    closed = account(AccountStatus.DEACTIVATED)

    with pytest.raises(InvalidStateTransitionError):
        closed.deactivated(reason=REASON)
    with pytest.raises(InvalidStateTransitionError):
        closed.reactivated()
    with pytest.raises(InvalidStateTransitionError):
        closed.suspended(reason=REASON)
