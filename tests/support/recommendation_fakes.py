"""Doubles and builders of the recommendations: in memory, no database."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import override
from uuid import UUID

from insumap.application.access.ports import PatientRecord
from insumap.application.ai.recommendations import (
    OpenPlanDraftPort,
    RecommendationFilter,
    RecommendationRepositoryPort,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.ai.recommendation import (
    DecisionRecord,
    Recommendation,
    SuggestedAction,
)
from insumap.domain.ai.recommendation_state import RecommendationStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.shared.errors import ErrorCode, InsumapError

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC = UUID(int=9)
DOCTOR = UUID(int=1)
OTHER_DOCTOR = UUID(int=2)
PATIENT = UUID(int=100)
RECOMMENDATION = UUID(int=500)
PLAN = UUID(int=600)
PROFILE = UUID(int=700)
DRAFT = UUID(int=800)


def make_recommendation(
    *,
    recommendation_id: UUID = RECOMMENDATION,
    status: RecommendationStatus = RecommendationStatus.PROPOSED,
    patient_id: UUID = PATIENT,
    expires_in: timedelta = timedelta(days=7),
    lock_version: int = 0,
) -> Recommendation:
    return Recommendation(
        recommendation_id=recommendation_id,
        clinic_id=CLINIC,
        patient_id=patient_id,
        plan_id=PLAN,
        target_profile_id=PROFILE,
        status=status,
        action=SuggestedAction.INCREASE,
        suggestion={
            "action": "INCREASE",
            "current_dose_units": 24.0,
            "proposed_dose_units": 26.0,
            "delta_units": 2.0,
            "rule_id": "FASTING_ABOVE_TARGET_NO_HYPO",
        },
        explanation={
            "summary": "Ayunos sobre la meta.",
            "factors": [],
            "data_refs": [],
        },
        model_name="titration-rules",
        model_version="0.1.0",
        input_hash="a" * 64,
        is_fallback=False,
        fallback_reason=None,
        proposed_at=NOW,
        expires_at=NOW + expires_in,
        generated_at=NOW,
        updated_at=NOW,
        lock_version=lock_version,
    )


def doctor(*, permissions: frozenset[PermissionCode] | None = None) -> Actor:
    return Actor(
        user_id=DOCTOR,
        clinic_id=CLINIC,
        role=Role.DOCTOR,
        permissions=permissions
        if permissions is not None
        else frozenset(
            {
                PermissionCode.RECOMMENDATIONS_DECIDE,
                PermissionCode.RECOMMENDATIONS_READ_ASSIGNED,
            }
        ),
        requires_mfa=True,
        mfa_verified=True,
    )


class InMemoryRecommendations(RecommendationRepositoryPort):
    def __init__(self, *items: Recommendation) -> None:
        self.items: dict[UUID, Recommendation] = {
            item.recommendation_id: item for item in items
        }
        self.decisions: list[tuple[UUID, DecisionRecord]] = []
        self.assignments: set[tuple[UUID, UUID]] = set()
        """(doctor, patient) pairs with an open assignment, as the database checks."""

    @override
    def get(self, recommendation_id: UUID) -> Recommendation | None:
        return self.items.get(recommendation_id)

    @override
    def list(
        self, filters: RecommendationFilter, page: PageRequest
    ) -> Page[Recommendation]:
        rows = [
            item
            for item in self.items.values()
            if (filters.patient_id is None or item.patient_id == filters.patient_id)
            and (filters.status is None or item.status is filters.status)
            and (
                filters.assigned_to is None
                or (filters.assigned_to, item.patient_id) in self.assignments
            )
        ]
        return build_page(
            rows, limit=page.limit, key=lambda item: item.recommendation_id
        )

    @override
    def save(
        self, recommendation: Recommendation, *, expected_lock_version: int
    ) -> bool:
        current = self.items[recommendation.recommendation_id]
        if current.lock_version != expected_lock_version:
            return False
        self.items[recommendation.recommendation_id] = recommendation
        return True

    @override
    def add_decision(
        self, recommendation: Recommendation, decision: DecisionRecord
    ) -> None:
        self.decisions.append((recommendation.recommendation_id, decision))

    @override
    def decisions_of(self, recommendation_id: UUID) -> Sequence[DecisionRecord]:
        return [d for rid, d in self.decisions if rid == recommendation_id]


class FakeDrafts(OpenPlanDraftPort):
    def __init__(self, *, has_active_plan: bool = True) -> None:
        self.has_active_plan = has_active_plan
        self.opened: list[UUID] = []

    @override
    def open_draft(self, patient_id: UUID, *, by: UUID, at: datetime) -> UUID | None:
        del by, at
        if not self.has_active_plan:
            return None
        self.opened.append(patient_id)
        return DRAFT


class FixedPatientGate:
    """Stands in for the assigned gate: grants the patients in ``assigned``."""

    def __init__(self, assigned: set[UUID]) -> None:
        self.assigned = assigned

    def enter(
        self,
        actor: Actor,
        permission: PermissionCode,
        patient_id: UUID,
        resource: object,
    ) -> UUID:
        del actor, permission, resource
        if patient_id not in self.assigned:
            raise InsumapError(ErrorCode.NOT_FOUND)
        return patient_id


def record(patient_id: UUID) -> PatientRecord:
    return PatientRecord(patient_id=patient_id, clinic_id=CLINIC)
