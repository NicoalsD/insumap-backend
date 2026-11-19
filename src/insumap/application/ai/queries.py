"""Reads of the recommendations: a doctor sees only the patients assigned to them."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.ai.recommendations import (
    RecommendationFilter,
    RecommendationRepositoryPort,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.ai.recommendation import DecisionRecord, Recommendation
from insumap.domain.ai.recommendation_state import RecommendationStatus
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode

READ_PERMISSION = PermissionCode.RECOMMENDATIONS_READ_ASSIGNED


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecommendationView:
    """A recommendation with the history of its decisions, oldest first."""

    recommendation: Recommendation
    decisions: Sequence[DecisionRecord]


@final
class ListRecommendationsUseCase:
    """``GET /recommendations``: one patient, or every assigned patient."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned_gate: AssignedPatientGate,
        recommendations: RecommendationRepositoryPort,
    ) -> None:
        self._uow = uow
        self._assigned = assigned_gate
        self._recommendations = recommendations

    def execute(
        self,
        actor: Actor,
        *,
        patient_id: UUID | None,
        status: RecommendationStatus | None,
        page: PageRequest,
    ) -> Page[Recommendation]:
        """One page, newest first. Each patient listed is audited (P09)."""
        actor.require(READ_PERMISSION)
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            if patient_id is not None:
                self._assigned.enter(
                    actor, READ_PERMISSION, patient_id, DataResource.AI_OUTPUTS
                )
                filters = RecommendationFilter(patient_id=patient_id, status=status)
            else:
                filters = RecommendationFilter(status=status, assigned_to=actor.user_id)
            result = self._recommendations.list(filters, page)
            if patient_id is None:
                for patient in sorted(
                    {item.patient_id for item in result.items}, key=str
                ):
                    self._assigned.enter(
                        actor, READ_PERMISSION, patient, DataResource.AI_OUTPUTS
                    )
            unit.commit()  # keeps the audit rows of the reads (P09)
        return result


@final
class GetRecommendationUseCase:
    """``GET /recommendations/{id}``: a recommendation and its decisions."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned_gate: AssignedPatientGate,
        recommendations: RecommendationRepositoryPort,
    ) -> None:
        self._uow = uow
        self._assigned = assigned_gate
        self._recommendations = recommendations

    def execute(self, actor: Actor, recommendation_id: UUID) -> RecommendationView:
        """The recommendation, or ``404`` when the doctor cannot see its patient."""
        actor.require(READ_PERMISSION)
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            recommendation = self._recommendations.get(recommendation_id)
            if recommendation is None:
                raise ResourceNotFoundError
            self._assigned.enter(
                actor,
                READ_PERMISSION,
                recommendation.patient_id,
                DataResource.AI_OUTPUTS,
            )
            decisions = tuple(self._recommendations.decisions_of(recommendation_id))
            unit.commit()  # keeps the audit row of the read (P09)
        return RecommendationView(recommendation=recommendation, decisions=decisions)
