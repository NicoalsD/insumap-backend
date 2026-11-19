"""P18 State: a recommendation accepts one decision while PROPOSED, then it is final."""

from datetime import timedelta

import pytest

from insumap.domain.ai.recommendation_state import (
    RecommendationState,
    RecommendationStatus,
)
from insumap.domain.common.errors import ReasonRequiredError
from insumap.domain.identity.errors import InvalidStateTransitionError
from tests.support.recommendation_fakes import (
    DOCTOR,
    NOW,
    make_recommendation,
)

REASON = "El ayuno fue producto de una cena tardía."


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("approve", RecommendationStatus.APPROVED),
        ("modify", RecommendationStatus.APPROVED_WITH_CHANGES),
        ("reject", RecommendationStatus.REJECTED),
    ],
)
def test_proposed_accepts_each_decision(
    action: str, expected: RecommendationStatus
) -> None:
    state = RecommendationState.from_status(RecommendationStatus.PROPOSED)

    assert getattr(state, action)().status is expected


@pytest.mark.parametrize(
    "status",
    [
        RecommendationStatus.APPROVED,
        RecommendationStatus.APPROVED_WITH_CHANGES,
        RecommendationStatus.REJECTED,
        RecommendationStatus.APPLIED,
        RecommendationStatus.EXPIRED,
    ],
)
@pytest.mark.parametrize("action", ["approve", "modify", "reject"])
def test_a_final_state_refuses_every_decision(
    status: RecommendationStatus, action: str
) -> None:
    state = RecommendationState.from_status(status)

    with pytest.raises(InvalidStateTransitionError) as caught:
        getattr(state, action)()

    assert caught.value.detail == {
        "machine": "recommendation",
        "status": status.value,
        "action": action,
    }


# Pattern: P18 State
def test_approve_moves_to_approved_and_keeps_the_history() -> None:
    moved, decision = make_recommendation().approve(by=DOCTOR, at=NOW)

    assert moved.status is RecommendationStatus.APPROVED
    assert moved.lock_version == 1
    assert decision.decision is RecommendationStatus.APPROVED
    assert decision.original_suggestion is not None
    assert decision.modified_suggestion is None


# Pattern: P18 State
def test_modify_keeps_the_original_and_the_change_with_a_reason() -> None:
    change = {"action": "INCREASE", "proposed_dose_units": 25.0, "delta_units": 1.0}

    moved, decision = make_recommendation().modify(
        modified=change, reason=REASON, by=DOCTOR, at=NOW
    )

    assert moved.status is RecommendationStatus.APPROVED_WITH_CHANGES
    assert moved.suggestion == change
    assert decision.original_suggestion is not None
    assert decision.original_suggestion["proposed_dose_units"] == 26.0
    assert decision.modified_suggestion == change
    assert decision.reason == REASON


# Pattern: P18 State
@pytest.mark.parametrize("reason", [None, "", "corto", "   "])
def test_modify_and_reject_need_a_reason(reason: str | None) -> None:
    recommendation = make_recommendation()

    with pytest.raises(ReasonRequiredError):
        recommendation.modify(modified={}, reason=reason, by=DOCTOR, at=NOW)
    with pytest.raises(ReasonRequiredError):
        recommendation.reject(reason=reason, by=DOCTOR, at=NOW)


# Pattern: P18 State
def test_reject_moves_to_rejected_with_the_reason() -> None:
    moved, decision = make_recommendation().reject(reason=REASON, by=DOCTOR, at=NOW)

    assert moved.status is RecommendationStatus.REJECTED
    assert decision.reason == REASON


# Pattern: P18 State
def test_a_proposal_past_its_deadline_cannot_be_decided() -> None:
    recommendation = make_recommendation(expires_in=timedelta(hours=1))

    with pytest.raises(InvalidStateTransitionError):
        recommendation.approve(by=DOCTOR, at=NOW + timedelta(hours=1))
