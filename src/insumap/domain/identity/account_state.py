"""Account state of a patient: ``IMPORTED -> INVITED -> ACTIVE <-> SUSPENDED``.

``docs/Actores-y-permisos.md``, section 5, holds the transition table. Any
non-terminal state can be deactivated; ``DEACTIVATED`` is terminal. The
security side effects of a transition (token version, refresh revocation) are
applied by the use case that confirms it, not by the state.
"""

from __future__ import annotations

from abc import ABC
from enum import StrEnum
from typing import ClassVar, Final, assert_never, final, override

from insumap.domain.identity.errors import InvalidStateTransitionError

MACHINE_NAME: Final = "patient_account"


class AccountStatus(StrEnum):
    """Persisted value of the account state (``iam.users.status``)."""

    IMPORTED = "IMPORTED"
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class PatientAccountState(ABC):
    """Base of the patient account machine: every action is refused by default.

    Each concrete state overrides only the actions it allows and returns the
    next state. ``from_status`` rebuilds a state from its persisted value.

    Pattern: P18 State
    """

    status: ClassVar[AccountStatus]
    can_sign_in: ClassVar[bool] = False

    def issue_credentials(self) -> PatientAccountState:
        """Issue (or re-issue) an activation invitation."""
        raise self._invalid("issue_credentials")

    def revoke_invitation(self) -> PatientAccountState:
        """Revoke or expire the pending invitation."""
        raise self._invalid("revoke_invitation")

    def activate(self) -> PatientAccountState:
        """Activate the account with the code and the accepted consent."""
        raise self._invalid("activate")

    def suspend(self) -> PatientAccountState:
        """Block the account temporarily."""
        raise self._invalid("suspend")

    def reactivate(self) -> PatientAccountState:
        """Lift a suspension."""
        raise self._invalid("reactivate")

    def deactivate(self) -> PatientAccountState:
        """Close the account for good."""
        raise self._invalid("deactivate")

    @final
    def _invalid(self, action: str) -> InvalidStateTransitionError:
        return InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)

    @staticmethod
    def from_status(status: AccountStatus) -> PatientAccountState:
        """Return the state object of a persisted status."""
        match status:
            case AccountStatus.IMPORTED:
                return ImportedState()
            case AccountStatus.INVITED:
                return InvitedState()
            case AccountStatus.ACTIVE:
                return ActiveState()
            case AccountStatus.SUSPENDED:
                return SuspendedState()
            case AccountStatus.DEACTIVATED:
                return DeactivatedState()
            case _:  # pragma: no cover - exhaustiveness guard for mypy
                assert_never(status)


class _DeactivatableState(PatientAccountState, ABC):
    """A non-terminal state: it can always be deactivated."""

    @override
    def deactivate(self) -> PatientAccountState:
        return DeactivatedState()


@final
class ImportedState(_DeactivatableState):
    """Imported from the clinic; no credentials yet."""

    status = AccountStatus.IMPORTED

    @override
    def issue_credentials(self) -> PatientAccountState:
        return InvitedState()


@final
class InvitedState(_DeactivatableState):
    """Has a pending single-use activation code."""

    status = AccountStatus.INVITED

    @override
    def issue_credentials(self) -> PatientAccountState:
        return InvitedState()

    @override
    def revoke_invitation(self) -> PatientAccountState:
        return ImportedState()

    @override
    def activate(self) -> PatientAccountState:
        return ActiveState()


@final
class ActiveState(_DeactivatableState):
    """Account in use: the only state that can sign in."""

    status = AccountStatus.ACTIVE
    can_sign_in = True

    @override
    def suspend(self) -> PatientAccountState:
        return SuspendedState()


@final
class SuspendedState(_DeactivatableState):
    """Temporarily blocked; sessions are revoked."""

    status = AccountStatus.SUSPENDED

    @override
    def reactivate(self) -> PatientAccountState:
        return ActiveState()


@final
class DeactivatedState(PatientAccountState):
    """Closed for good (terminal)."""

    status = AccountStatus.DEACTIVATED
