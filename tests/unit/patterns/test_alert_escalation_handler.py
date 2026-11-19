"""P12 Chain of Responsibility: an alert reaches the next link when nobody answers."""

from uuid import UUID

import pytest

from insumap.domain.alerts.escalation import (
    EscalationContext,
    build_escalation_chain,
    parse_escalation,
)
from insumap.shared.errors import InsumapError

PATIENT = UUID(int=1)
DOCTOR = UUID(int=2)
TEAM = UUID(int=3)
ADMIN = UUID(int=4)


def context(**overrides: object) -> EscalationContext:
    values: dict[str, object] = {
        "patient_user_id": PATIENT,
        "primary_doctor_id": DOCTOR,
        "team_doctor_ids": (TEAM,),
        "clinic_admin_ids": (ADMIN,),
    }
    values.update(overrides)
    return EscalationContext(**values)  # type: ignore[arg-type]


def test_from_level_one_skips_the_patient_link() -> None:
    outcome = build_escalation_chain().escalate(context(), from_level=1)

    assert outcome is not None
    assert outcome.level == 1
    assert outcome.recipients == (DOCTOR,)


def test_a_level_without_recipients_passes_to_the_next_one() -> None:
    outcome = build_escalation_chain().escalate(
        context(primary_doctor_id=None), from_level=1
    )

    assert outcome is not None
    assert outcome.level == 2
    assert outcome.recipients == (TEAM,)


def test_nobody_to_reach_answers_none() -> None:
    nobody = context(
        patient_user_id=None,
        primary_doctor_id=None,
        team_doctor_ids=(),
        clinic_admin_ids=(),
    )

    assert build_escalation_chain().escalate(nobody, from_level=0) is None


def test_steps_must_be_consecutive_and_match_their_recipient() -> None:
    steps = parse_escalation(
        [
            {"level": 1, "recipient": "PRIMARY_DOCTOR", "wait_minutes": 15},
            {"level": 2, "recipient": "CARE_TEAM", "wait_minutes": 30},
        ]
    )

    assert [s.level for s in steps] == [1, 2]
    with pytest.raises(InsumapError):
        parse_escalation([{"level": 2, "recipient": "CARE_TEAM", "wait_minutes": 30}])
    with pytest.raises(InsumapError):
        parse_escalation([{"level": 1, "recipient": "CARE_TEAM", "wait_minutes": 30}])
