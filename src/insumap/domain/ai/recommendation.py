"""A treatment proposal of the AI (``ai.recommendations``) and the doctor's decisions.

The AI never gives a dose to the patient: a recommendation is born ``PROPOSED`` and
changes the plan only through an approval that the doctor makes (docs/Modulo-IA 3.2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, final
from uuid import UUID

from insumap.domain.ai.recommendation_state import (
    MACHINE_NAME,
    RecommendationState,
    RecommendationStatus,
)
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import InvalidStateTransitionError


class SuggestedAction(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionRecord:
    """One row of ``ai.recommendation_decisions``: an append only transition."""

    decision: RecommendationStatus
    decided_by: UUID
    decided_at: datetime
    reason: str | None
    original_suggestion: Mapping[str, Any] | None
    modified_suggestion: Mapping[str, Any] | None
    model_version: str


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Recommendation:
    """A proposal with its status, its model trail and its lock version."""

    recommendation_id: UUID
    clinic_id: UUID
    patient_id: UUID
    plan_id: UUID
    target_profile_id: UUID
    status: RecommendationStatus
    action: SuggestedAction
    suggestion: Mapping[str, Any]
    explanation: Mapping[str, Any]
    model_name: str
    model_version: str
    input_hash: str
    is_fallback: bool
    fallback_reason: str | None
    proposed_at: datetime
    expires_at: datetime
    generated_at: datetime
    updated_at: datetime
    lock_version: int

    @property
    def state(self) -> RecommendationState:
        return RecommendationState.from_status(self.status)

    def approve(
        self, *, by: UUID, at: datetime
    ) -> tuple[Recommendation, DecisionRecord]:
        """Accept the proposal as it is."""
        self._ensure_open(at, "approve")
        next_state = self.state.approve()
        return self._moved(
            next_state.status,
            at,
            DecisionRecord(
                decision=next_state.status,
                decided_by=by,
                decided_at=at,
                reason=None,
                original_suggestion=dict(self.suggestion),
                modified_suggestion=None,
                model_version=self.model_version,
            ),
        )

    def modify(
        self,
        *,
        modified: Mapping[str, Any],
        reason: str | None,
        by: UUID,
        at: datetime,
    ) -> tuple[Recommendation, DecisionRecord]:
        """Accept a change of the proposal; the original and the change are kept."""
        self._ensure_open(at, "modify")
        note = Reason.parse(reason).text
        next_state = self.state.modify()
        return self._moved(
            next_state.status,
            at,
            DecisionRecord(
                decision=next_state.status,
                decided_by=by,
                decided_at=at,
                reason=note,
                original_suggestion=dict(self.suggestion),
                modified_suggestion=dict(modified),
                model_version=self.model_version,
            ),
            suggestion=dict(modified),
        )

    def reject(
        self, *, reason: str | None, by: UUID, at: datetime
    ) -> tuple[Recommendation, DecisionRecord]:
        """Refuse the proposal, with the reason that is mandatory here."""
        self._ensure_open(at, "reject")
        note = Reason.parse(reason).text
        next_state = self.state.reject()
        return self._moved(
            next_state.status,
            at,
            DecisionRecord(
                decision=next_state.status,
                decided_by=by,
                decided_at=at,
                reason=note,
                original_suggestion=dict(self.suggestion),
                modified_suggestion=None,
                model_version=self.model_version,
            ),
        )

    def _ensure_open(self, at: datetime, action: str) -> None:
        """A proposal past its deadline is refused, even if it still says PROPOSED."""
        if self.status is RecommendationStatus.PROPOSED and at >= self.expires_at:
            raise InvalidStateTransitionError(
                MACHINE_NAME, RecommendationStatus.EXPIRED.value, action
            )

    def _moved(
        self,
        status: RecommendationStatus,
        at: datetime,
        decision: DecisionRecord,
        *,
        suggestion: Mapping[str, Any] | None = None,
    ) -> tuple[Recommendation, DecisionRecord]:
        moved = Recommendation(
            recommendation_id=self.recommendation_id,
            clinic_id=self.clinic_id,
            patient_id=self.patient_id,
            plan_id=self.plan_id,
            target_profile_id=self.target_profile_id,
            status=status,
            action=self.action,
            suggestion=self.suggestion if suggestion is None else suggestion,
            explanation=self.explanation,
            model_name=self.model_name,
            model_version=self.model_version,
            input_hash=self.input_hash,
            is_fallback=self.is_fallback,
            fallback_reason=self.fallback_reason,
            proposed_at=self.proposed_at,
            expires_at=self.expires_at,
            generated_at=self.generated_at,
            updated_at=at,
            lock_version=self.lock_version + 1,
        )
        return moved, decision
