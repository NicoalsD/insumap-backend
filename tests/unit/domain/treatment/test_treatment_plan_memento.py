"""P16 Memento: TreatmentPlan.create_memento() and from_memento()."""

import json
from datetime import time
from decimal import Decimal

from insumap.domain.treatment.content import TitrationRules
from insumap.domain.treatment.plan import PlanStatus, TreatmentPlan
from tests.unit.domain.treatment.factories import (
    AT,
    LATER,
    draft,
    insulin,
    measure,
    plan_items,
    uid,
)


def test_the_memento_holds_only_primitives_and_survives_json() -> None:
    plan = draft(*plan_items(insulin(units="7.5"), measure()), notes="Inicio")

    memento = plan.create_memento(taken_at=LATER)

    text = json.dumps(memento.data)
    assert json.loads(text) == memento.data
    assert memento.taken_at == LATER
    assert memento.schema_version == 1
    assert memento.data["items"][0]["dose_units"] == "7.5"


def test_restoring_a_memento_rebuilds_the_same_plan() -> None:
    plan = draft(*plan_items(insulin(units="7.5"), measure()), notes="Inicio")

    restored = TreatmentPlan.from_memento(plan.create_memento(taken_at=LATER))

    assert restored.plan_id == plan.plan_id
    assert restored.version == plan.version
    assert restored.status is PlanStatus.DRAFT
    assert restored.items == plan.items
    assert restored.titration_rules == plan.titration_rules
    assert restored.notes == "Inicio"
    assert restored.target_profile_id == plan.target_profile_id


def test_the_memento_keeps_the_decimal_and_the_time_exactly() -> None:
    plan = draft(*plan_items(insulin(units="0.25", at="06:45")))

    restored = TreatmentPlan.from_memento(plan.create_memento(taken_at=AT))

    assert restored.items[0].dose_units == Decimal("0.25")
    assert restored.items[0].time_of_day == time(6, 45)


def test_a_memento_without_titration_rules_or_items_round_trips() -> None:
    plan = TreatmentPlan.draft(
        plan_id=uid(9),
        clinic_id=uid(1),
        patient_id=uid(2),
        version=1,
        target_profile_id=uid(4),
        created_by=uid(3),
        at=AT,
        items=(),
    )

    restored = TreatmentPlan.from_memento(plan.create_memento(taken_at=AT))

    assert restored.items == ()
    assert restored.titration_rules is None


def test_restoring_then_copying_yields_a_draft_with_new_ids() -> None:
    plan = draft(*plan_items(insulin(), measure())).activate(by=uid(3), at=AT)
    snapshot = plan.create_memento(taken_at=LATER)

    copy = TreatmentPlan.from_memento(snapshot).copy_for_new_version(
        new_plan_id=uid(70),
        item_ids=(uid(71), uid(72)),
        version=2,
        created_by=uid(3),
        at=LATER,
    )

    assert copy.status is PlanStatus.DRAFT
    assert copy.previous_plan_id == plan.plan_id
    assert [item.item_id for item in copy.items] == [uid(71), uid(72)]
    assert copy.titration_rules == TitrationRules(
        step_units=Decimal("1"),
        max_change_units=Decimal("4"),
        min_days_between_adjustments=3,
    )
