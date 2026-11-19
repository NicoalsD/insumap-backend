"""The life of a recommendation (P18 State): PROPOSED, then one final decision.

``PROPOSED`` is the only state that accepts a decision: the doctor approves,
approves with changes or rejects. ``APPROVED``, ``APPROVED_WITH_CHANGES``,
``REJECTED``, ``APPLIED`` and ``EXPIRED`` are final for decisions. ``APPLIED``
happens when the draft plan of an approval is activated, outside this machine.
The persisted value is the ``RecommendationStatus``; ``RecommendationState.from_status``
is the only ``match`` over the statuses.
"""

from __future__ import annotations

from abc import ABC
from enum import StrEnum
from typing import ClassVar, assert_never, final, override

from insumap.domain.identity.errors import InvalidStateTransitionError

MACHINE_NAME = "recommendation"


class RecommendationStatus(StrEnum):
    """Stored status of a recommendation (``ai.recommendations.status``)."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPROVED_WITH_CHANGES = "APPROVED_WITH_CHANGES"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"


class RecommendationState(ABC):
    """Base of the recommendation machine. Every action not overridden is refused.

    Pattern: P18 State
    """

    status: ClassVar[RecommendationStatus]

    def approve(self) -> RecommendationState:
        """The doctor accepts the proposal as it is."""
        raise self._invalid("approve")

    def modify(self) -> RecommendationState:
        """The doctor changes the proposal and accepts the change."""
        raise self._invalid("modify")

    def reject(self) -> RecommendationState:
        """The doctor rejects the proposal, with a reason."""
        raise self._invalid("reject")

    def _invalid(self, action: str) -> InvalidStateTransitionError:
        return InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)

    @staticmethod
    def from_status(status: RecommendationStatus) -> RecommendationState:
        """The state object of a stored status."""
        match status:
            case RecommendationStatus.PROPOSED:
                return ProposedRecommendationState()
            case RecommendationStatus.APPROVED:
                return ApprovedRecommendationState()
            case RecommendationStatus.APPROVED_WITH_CHANGES:
                return ApprovedWithChangesRecommendationState()
            case RecommendationStatus.REJECTED:
                return RejectedRecommendationState()
            case RecommendationStatus.APPLIED:
                return AppliedRecommendationState()
            case RecommendationStatus.EXPIRED:
                return ExpiredRecommendationState()
            case _:
                assert_never(status)


@final
class ProposedRecommendationState(RecommendationState):
    status = RecommendationStatus.PROPOSED

    @override
    def approve(self) -> RecommendationState:
        return ApprovedRecommendationState()

    @override
    def modify(self) -> RecommendationState:
        return ApprovedWithChangesRecommendationState()

    @override
    def reject(self) -> RecommendationState:
        return RejectedRecommendationState()


@final
class ApprovedRecommendationState(RecommendationState):
    status = RecommendationStatus.APPROVED


@final
class ApprovedWithChangesRecommendationState(RecommendationState):
    status = RecommendationStatus.APPROVED_WITH_CHANGES


@final
class RejectedRecommendationState(RecommendationState):
    status = RecommendationStatus.REJECTED


@final
class AppliedRecommendationState(RecommendationState):
    status = RecommendationStatus.APPLIED


@final
class ExpiredRecommendationState(RecommendationState):
    status = RecommendationStatus.EXPIRED
