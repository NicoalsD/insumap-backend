"""P18 State: the alert machine accepts only the transitions the documents allow."""

import pytest

from insumap.domain.alerts.state import AlertState, AlertStatus
from insumap.domain.identity.errors import InvalidStateTransitionError


@pytest.mark.parametrize(
    ("status", "action", "target"),
    [
        (AlertStatus.OPEN, "acknowledge", AlertStatus.ACKNOWLEDGED),
        (AlertStatus.OPEN, "escalate", AlertStatus.ESCALATED),
        (AlertStatus.ESCALATED, "acknowledge", AlertStatus.ACKNOWLEDGED),
        (AlertStatus.ESCALATED, "escalate", AlertStatus.ESCALATED),
        (AlertStatus.ACKNOWLEDGED, "resolve", AlertStatus.RESOLVED),
    ],
)
def test_allowed_transitions_reach_the_target(
    status: AlertStatus, action: str, target: AlertStatus
) -> None:
    state = AlertState.from_status(status)

    assert getattr(state, action)().status is target


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (AlertStatus.OPEN, "resolve"),
        (AlertStatus.ESCALATED, "resolve"),
        (AlertStatus.ACKNOWLEDGED, "acknowledge"),
        (AlertStatus.ACKNOWLEDGED, "escalate"),
        (AlertStatus.RESOLVED, "acknowledge"),
        (AlertStatus.RESOLVED, "resolve"),
        (AlertStatus.RESOLVED, "escalate"),
    ],
)
def test_refused_transitions_name_the_machine_and_the_status(
    status: AlertStatus, action: str
) -> None:
    state = AlertState.from_status(status)

    with pytest.raises(InvalidStateTransitionError) as refused:
        getattr(state, action)()

    assert refused.value.detail == {
        "machine": "alert",
        "status": status.value,
        "action": action,
    }


def test_from_status_covers_every_stored_status() -> None:
    assert {AlertState.from_status(s).status for s in AlertStatus} == set(AlertStatus)
