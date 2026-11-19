"""Privacy requests of a patient (RF-93) and their lifecycle (P18 State)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, final, override
from uuid import UUID

from insumap.domain.identity.errors import InvalidStateTransitionError

MACHINE_NAME = "PRIVACY_REQUEST"


class PrivacyRequestType(StrEnum):
    """What the patient asks (``clinic.privacy_requests.request_type``)."""

    ACCESS = "ACCESS"
    RECTIFICATION = "RECTIFICATION"
    ERASURE = "ERASURE"
    CONSENT_WITHDRAWAL = "CONSENT_WITHDRAWAL"


class PrivacyRequestStatus(StrEnum):
    """Lifecycle of a request (``clinic.privacy_requests.status``)."""

    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class PrivacyDecision(StrEnum):
    """What the clinic decides on an open request."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class PrivacyRequestState(ABC):
    """One state of a privacy request: which decisions and reads it allows.

    Pattern: P18 State
    """

    status: ClassVar[PrivacyRequestStatus]

    @abstractmethod
    def decide(self, decision: PrivacyDecision) -> PrivacyRequestStatus:
        """The status after ``decision``; raise if the state refuses it."""

    @property
    def exportable(self) -> bool:
        """Whether the patient may export the data under this request."""
        return False

    def _refuse(self, action: str) -> InvalidStateTransitionError:
        return InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)


class _Pending(PrivacyRequestState):
    """States where the clinic still has to decide."""

    @override
    def decide(self, decision: PrivacyDecision) -> PrivacyRequestStatus:
        if decision is PrivacyDecision.APPROVE:
            return PrivacyRequestStatus.APPROVED
        return PrivacyRequestStatus.REJECTED


@final
class OpenState(_Pending):
    """Received, not yet being handled. Pattern: P18 State"""

    status = PrivacyRequestStatus.OPEN


@final
class InProgressState(_Pending):
    """Being handled by the clinic. Pattern: P18 State"""

    status = PrivacyRequestStatus.IN_PROGRESS


@final
class ApprovedState(PrivacyRequestState):
    """Approved: the patient may export its data. Pattern: P18 State"""

    status = PrivacyRequestStatus.APPROVED

    @override
    def decide(self, decision: PrivacyDecision) -> PrivacyRequestStatus:
        raise self._refuse(decision.value)

    @property
    @override
    def exportable(self) -> bool:
        return True


@final
class RejectedState(PrivacyRequestState):
    """Rejected with a note. Terminal. Pattern: P18 State"""

    status = PrivacyRequestStatus.REJECTED

    @override
    def decide(self, decision: PrivacyDecision) -> PrivacyRequestStatus:
        raise self._refuse(decision.value)


@final
class CompletedState(PrivacyRequestState):
    """Fulfilled. Terminal. Pattern: P18 State"""

    status = PrivacyRequestStatus.COMPLETED

    @override
    def decide(self, decision: PrivacyDecision) -> PrivacyRequestStatus:
        raise self._refuse(decision.value)


PRIVACY_REQUEST_STATES: Mapping[PrivacyRequestStatus, PrivacyRequestState] = {
    state.status: state
    for state in (
        OpenState(),
        InProgressState(),
        ApprovedState(),
        RejectedState(),
        CompletedState(),
    )
}


def state_of(status: PrivacyRequestStatus) -> PrivacyRequestState:
    """The state object of a status stored in the database."""
    return PRIVACY_REQUEST_STATES[status]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PrivacyRequest:
    """One request of a patient, with the deadline the clinic must meet."""

    request_id: UUID
    clinic_id: UUID
    patient_id: UUID
    request_type: PrivacyRequestType
    status: PrivacyRequestStatus
    requested_at: datetime
    due_at: datetime
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    resolution_note: str | None = None

    def decide(
        self,
        decision: PrivacyDecision,
        *,
        note: str,
        resolver: UUID,
        at: datetime,
    ) -> PrivacyRequest:
        """The request after the clinic's decision; the state refuses bad moves."""
        status = state_of(self.status).decide(decision)
        return replace(
            self,
            status=status,
            resolved_at=at,
            resolved_by=resolver,
            resolution_note=note,
        )

    @property
    def exportable(self) -> bool:
        """Whether the patient may export its data under this request."""
        return state_of(self.status).exportable
