"""``ai.recommendations`` and its decisions, under row level security."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast, final, override
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from insumap.application.ai.recommendations import (
    RecommendationFilter,
    RecommendationRepositoryPort,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.ai.recommendation import (
    DecisionRecord,
    Recommendation,
    SuggestedAction,
)
from insumap.domain.ai.recommendation_state import RecommendationStatus
from insumap.infrastructure.persistence.orm import (
    CareAssignmentOrm,
    RecommendationDecisionOrm,
    RecommendationOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@final
class RecommendationRepository(RecommendationRepositoryPort):
    """The doctor and the system work on their clinic; the policies do the rest."""

    def __init__(self, current: CurrentSession, ids: IdGenerator) -> None:
        self._current = current
        self._ids = ids

    @override
    def get(self, recommendation_id: UUID) -> Recommendation | None:
        row = self._current.get().get(RecommendationOrm, recommendation_id)
        return None if row is None else _recommendation(row)

    @override
    def list(
        self, filters: RecommendationFilter, page: PageRequest
    ) -> Page[Recommendation]:
        statement = select(RecommendationOrm).order_by(RecommendationOrm.id.desc())
        if page.after is not None:
            statement = statement.where(RecommendationOrm.id < page.after)
        if filters.patient_id is not None:
            statement = statement.where(
                RecommendationOrm.patient_id == filters.patient_id
            )
        if filters.status is not None:
            statement = statement.where(
                RecommendationOrm.status == filters.status.value
            )
        if filters.assigned_to is not None:
            statement = statement.where(
                RecommendationOrm.patient_id.in_(
                    select(CareAssignmentOrm.patient_id).where(
                        CareAssignmentOrm.doctor_user_id == filters.assigned_to,
                        CareAssignmentOrm.ended_at.is_(None),
                    )
                )
            )
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_recommendation(row) for row in rows],
            limit=page.limit,
            key=lambda item: item.recommendation_id,
        )

    @override
    def save(
        self, recommendation: Recommendation, *, expected_lock_version: int
    ) -> bool:
        result = cast(
            CursorResult[Any],
            self._current.get().execute(
                update(RecommendationOrm)
                .where(
                    RecommendationOrm.id == recommendation.recommendation_id,
                    RecommendationOrm.lock_version == expected_lock_version,
                )
                .values(
                    status=recommendation.status.value,
                    suggestion=dict(recommendation.suggestion),
                    updated_at=recommendation.updated_at,
                    lock_version=recommendation.lock_version,
                )
            ),
        )
        rowcount: int = result.rowcount
        return rowcount == 1

    @override
    def add_decision(
        self, recommendation: Recommendation, decision: DecisionRecord
    ) -> None:
        self._current.get().add(
            RecommendationDecisionOrm(
                id=self._ids.new_id(),
                clinic_id=recommendation.clinic_id,
                recommendation_id=recommendation.recommendation_id,
                decision=decision.decision.value,
                decided_by=decision.decided_by,
                decided_at=decision.decided_at,
                reason=decision.reason,
                reason_code=None,
                original_suggestion=_optional(decision.original_suggestion),
                modified_suggestion=_optional(decision.modified_suggestion),
                model_version=decision.model_version,
                applied_plan_id=None,
            )
        )
        self._current.get().flush()

    @override
    def decisions_of(self, recommendation_id: UUID) -> Sequence[DecisionRecord]:
        rows = (
            self._current.get()
            .scalars(
                select(RecommendationDecisionOrm)
                .where(RecommendationDecisionOrm.recommendation_id == recommendation_id)
                .order_by(RecommendationDecisionOrm.decided_at)
            )
            .all()
        )
        return [_decision(row) for row in rows]


def _recommendation(row: RecommendationOrm) -> Recommendation:
    return Recommendation(
        recommendation_id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        plan_id=row.plan_id,
        target_profile_id=row.target_profile_id,
        status=RecommendationStatus(row.status),
        action=SuggestedAction(row.action),
        suggestion=dict(row.suggestion),
        explanation=dict(row.explanation),
        model_name=row.model_name,
        model_version=row.model_version,
        input_hash=row.input_hash,
        is_fallback=row.is_fallback,
        fallback_reason=row.fallback_reason,
        proposed_at=row.proposed_at,
        expires_at=row.expires_at,
        generated_at=row.generated_at,
        updated_at=row.updated_at,
        lock_version=row.lock_version,
    )


def _decision(row: RecommendationDecisionOrm) -> DecisionRecord:
    return DecisionRecord(
        decision=RecommendationStatus(row.decision),
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        reason=row.reason,
        original_suggestion=row.original_suggestion,
        modified_suggestion=row.modified_suggestion,
        model_version=row.model_version,
    )


def _optional(value: Any) -> dict[str, Any] | None:
    return None if value is None else dict(value)
