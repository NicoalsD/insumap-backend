"""P13 Command: the doctor's decisions on a recommendation, without a database."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

import pytest

from insumap.application.ai.commands import (
    ApproveRecommendationCommand,
    ApproveRecommendationCommandHandler,
    ModifyRecommendationCommand,
    ModifyRecommendationCommandHandler,
    RejectRecommendationCommand,
    RejectRecommendationCommandHandler,
)
from insumap.application.commands.transactional import CurrentUnitOfWork
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWork
from insumap.domain.ai.events import RecommendationApproved
from insumap.domain.ai.recommendation_state import RecommendationStatus
from insumap.domain.common.errors import ConflictError, ReasonRequiredError
from insumap.domain.common.events import DomainEvent
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.identity_fakes import FakeIds
from tests.support.recommendation_fakes import (
    NOW,
    PATIENT,
    RECOMMENDATION,
    FakeDrafts,
    FixedPatientGate,
    InMemoryRecommendations,
    doctor,
    make_recommendation,
)

REASON = "El ayuno fue producto de una cena tardía."
MODIFIED = {"action": "INCREASE", "proposed_dose_units": 25.0, "delta_units": 1.0}


class RecordingUnit(UnitOfWork):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def apply_context(self, context: TransactionContext) -> None:
        del context

    def collect(self, events: Sequence[DomainEvent]) -> None:
        self.events.extend(events)

    def commit(self) -> None:
        return None


class Harness:
    def __init__(
        self, *, assigned: set[UUID] | None = None, has_plan: bool = True
    ) -> None:
        self.repo = InMemoryRecommendations(make_recommendation())
        self.drafts = FakeDrafts(has_active_plan=has_plan)
        self.gate = FixedPatientGate({PATIENT} if assigned is None else assigned)
        self.current = CurrentUnitOfWork()
        self.unit = RecordingUnit()
        self.clock = _Clock(NOW)
        self.ids = FakeIds()

    def run(self, handler: object, command: object) -> object:
        with self.current.bind(self.unit):
            return handler.handle(command)  # type: ignore[attr-defined]

    def approve_handler(self) -> ApproveRecommendationCommandHandler:
        return ApproveRecommendationCommandHandler(
            recommendations=self.repo,
            assigned_gate=self.gate,  # type: ignore[arg-type]
            drafts=self.drafts,
            clock=self.clock,
            current=self.current,
            ids=self.ids,
        )

    def modify_handler(self) -> ModifyRecommendationCommandHandler:
        return ModifyRecommendationCommandHandler(
            recommendations=self.repo,
            assigned_gate=self.gate,  # type: ignore[arg-type]
            drafts=self.drafts,
            clock=self.clock,
            current=self.current,
            ids=self.ids,
        )

    def reject_handler(self) -> RejectRecommendationCommandHandler:
        return RejectRecommendationCommandHandler(
            recommendations=self.repo,
            assigned_gate=self.gate,  # type: ignore[arg-type]
            clock=self.clock,
            current=self.current,
            ids=self.ids,
        )


def _always_stale(recommendation: object, *, expected_lock_version: int) -> bool:
    del recommendation, expected_lock_version
    return False


class _Clock:
    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


# Pattern: P13 Command
def test_approve_records_the_decision_opens_a_draft_and_publishes_after_collect() -> (
    None
):
    harness = Harness()

    result = harness.run(
        harness.approve_handler(),
        ApproveRecommendationCommand(actor=doctor(), recommendation_id=RECOMMENDATION),
    )

    assert result.recommendation.status is RecommendationStatus.APPROVED  # type: ignore[attr-defined]
    assert result.draft_plan_id is not None  # type: ignore[attr-defined]
    assert harness.drafts.opened == [PATIENT]
    (event,) = harness.unit.events
    assert isinstance(event, RecommendationApproved)
    assert event.status is RecommendationStatus.APPROVED
    assert event.recommendation_id == RECOMMENDATION
    assert len(harness.repo.decisions) == 1


# Pattern: P13 Command
def test_approve_without_an_active_plan_opens_no_draft_but_still_approves() -> None:
    harness = Harness(has_plan=False)

    result = harness.run(
        harness.approve_handler(),
        ApproveRecommendationCommand(actor=doctor(), recommendation_id=RECOMMENDATION),
    )

    assert result.draft_plan_id is None  # type: ignore[attr-defined]
    assert result.recommendation.status is RecommendationStatus.APPROVED  # type: ignore[attr-defined]


# Pattern: P13 Command
def test_modify_keeps_the_original_and_the_change_and_publishes() -> None:
    harness = Harness()

    result = harness.run(
        harness.modify_handler(),
        ModifyRecommendationCommand(
            actor=doctor(),
            recommendation_id=RECOMMENDATION,
            modified_proposal=MODIFIED,
            reason=REASON,
        ),
    )

    assert result.recommendation.status is RecommendationStatus.APPROVED_WITH_CHANGES  # type: ignore[attr-defined]
    _, decision = harness.repo.decisions[0]
    assert decision.modified_suggestion == MODIFIED
    assert decision.reason == REASON
    assert isinstance(harness.unit.events[0], RecommendationApproved)


# Pattern: P13 Command
def test_reject_needs_a_reason_and_opens_no_draft() -> None:
    harness = Harness()

    with pytest.raises(ReasonRequiredError):
        harness.run(
            harness.reject_handler(),
            RejectRecommendationCommand(
                actor=doctor(), recommendation_id=RECOMMENDATION, reason="corto"
            ),
        )
    assert harness.repo.decisions == []

    result = harness.run(
        harness.reject_handler(),
        RejectRecommendationCommand(
            actor=doctor(), recommendation_id=RECOMMENDATION, reason=REASON
        ),
    )

    assert result.recommendation.status is RecommendationStatus.REJECTED  # type: ignore[attr-defined]
    assert harness.drafts.opened == []
    assert harness.unit.events == []


# Pattern: P13 Command
def test_a_decided_recommendation_refuses_a_second_decision() -> None:
    harness = Harness()
    harness.run(
        harness.approve_handler(),
        ApproveRecommendationCommand(actor=doctor(), recommendation_id=RECOMMENDATION),
    )

    with pytest.raises(InvalidStateTransitionError):
        harness.run(
            harness.reject_handler(),
            RejectRecommendationCommand(
                actor=doctor(), recommendation_id=RECOMMENDATION, reason=REASON
            ),
        )


# Pattern: P13 Command
def test_a_doctor_without_the_permission_is_refused() -> None:
    harness = Harness()
    actor = doctor(permissions=frozenset())

    with pytest.raises(PermissionDeniedError):
        harness.run(
            harness.approve_handler(),
            ApproveRecommendationCommand(actor=actor, recommendation_id=RECOMMENDATION),
        )


# Pattern: P13 Command
def test_an_unassigned_patient_answers_the_same_not_found_as_a_missing_one() -> None:
    harness = Harness(assigned=set())

    with pytest.raises(InsumapError) as caught:
        harness.run(
            harness.approve_handler(),
            ApproveRecommendationCommand(
                actor=doctor(), recommendation_id=RECOMMENDATION
            ),
        )

    assert caught.value.code is ErrorCode.NOT_FOUND
    assert harness.repo.decisions == []


# Pattern: P13 Command
def test_a_missing_recommendation_is_not_found() -> None:
    harness = Harness()

    with pytest.raises(InsumapError) as caught:
        harness.run(
            harness.approve_handler(),
            ApproveRecommendationCommand(actor=doctor(), recommendation_id=UUID(int=1)),
        )

    assert caught.value.code is ErrorCode.NOT_FOUND


# Pattern: P13 Command
def test_a_stale_lock_version_is_a_conflict() -> None:
    harness = Harness()
    stale = make_recommendation(lock_version=3)
    harness.repo.items[RECOMMENDATION] = stale
    harness.repo.save = _always_stale  # type: ignore[method-assign]

    with pytest.raises(ConflictError):
        harness.run(
            harness.approve_handler(),
            ApproveRecommendationCommand(
                actor=doctor(), recommendation_id=RECOMMENDATION
            ),
        )
