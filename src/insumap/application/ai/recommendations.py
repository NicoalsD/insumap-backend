"""Ports and reads of the recommendations: the doctor sees only assigned patients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.ai.recommendation import DecisionRecord, Recommendation
from insumap.domain.ai.recommendation_state import RecommendationStatus


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecommendationFilter:
    """The optional filters of ``GET /recommendations``.

    ``assigned_to`` limits the list to the open assignments of a doctor; row level
    security does not do it (it allows every recommendation of the clinic).
    """

    patient_id: UUID | None = None
    status: RecommendationStatus | None = None
    assigned_to: UUID | None = None


class RecommendationRepositoryPort(ABC):
    """``ai.recommendations`` and its decisions, as the session sees them."""

    @abstractmethod
    def get(self, recommendation_id: UUID) -> Recommendation | None:
        """A recommendation the session can see, or ``None``."""

    @abstractmethod
    def list(
        self, filters: RecommendationFilter, page: PageRequest
    ) -> Page[Recommendation]:
        """A page of recommendations, newest first."""

    @abstractmethod
    def save(
        self, recommendation: Recommendation, *, expected_lock_version: int
    ) -> bool:
        """Update the status if the lock version is still the expected one."""

    @abstractmethod
    def add_decision(
        self, recommendation: Recommendation, decision: DecisionRecord
    ) -> None:
        """Append one decision; the table is append only."""

    @abstractmethod
    def decisions_of(self, recommendation_id: UUID) -> Sequence[DecisionRecord]:
        """Every decision of a recommendation, oldest first."""


class OpenPlanDraftPort(ABC):
    """Opens the draft of the next treatment plan version of a patient (P05)."""

    @abstractmethod
    def open_draft(self, patient_id: UUID, *, by: UUID, at: datetime) -> UUID | None:
        """The id of the new draft, or ``None`` if the patient has no active plan."""
