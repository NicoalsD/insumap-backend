"""Events of the AI decisions (P17), published after the commit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.domain.ai.recommendation_state import RecommendationStatus
from insumap.domain.common.events import DomainEvent


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecommendationApproved(DomainEvent):
    """A doctor accepted a proposal, as is or with changes (committed).

    Pattern: P17 Observer. It carries identifiers and the status, never doses.
    """

    recommendation_id: UUID
    patient_id: UUID
    clinic_id: UUID
    status: RecommendationStatus
