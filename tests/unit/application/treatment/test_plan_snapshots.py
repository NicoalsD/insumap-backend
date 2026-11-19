"""P16 Memento: the caretaker keeps a photo before each change and never reads it."""

from insumap.application.treatment.snapshots import PlanSnapshotCaretaker
from insumap.domain.treatment.plan import TreatmentPlan
from tests.support.treatment_fakes import FakeSnapshots
from tests.unit.domain.treatment.factories import (
    AT,
    DOCTOR,
    LATER,
    draft,
    insulin,
    plan_items,
)


def test_each_change_adds_one_photo_numbered_in_order() -> None:
    snapshots = FakeSnapshots()
    caretaker = PlanSnapshotCaretaker(snapshots)
    plan = draft(*plan_items(insulin()))

    caretaker.before_change(plan, taken_by=DOCTOR, at=AT)
    caretaker.before_change(plan, taken_by=DOCTOR, at=LATER)

    assert [row.number for row in snapshots.rows] == [1, 2]
    assert [row.memento.taken_at for row in snapshots.rows] == [AT, LATER]
    assert all(row.plan_id == plan.plan_id for row in snapshots.rows)
    assert all(row.taken_by == DOCTOR for row in snapshots.rows)


def test_the_photo_is_the_plan_as_it_was_when_taken() -> None:
    snapshots = FakeSnapshots()
    plan = draft(*plan_items(insulin(units="3")))

    PlanSnapshotCaretaker(snapshots).before_change(plan, taken_by=DOCTOR, at=AT)
    later = plan.with_content(
        items=plan_items(insulin(units="9")), titration_rules=None, notes=None, at=LATER
    )

    restored = TreatmentPlan.from_memento(snapshots.rows[0].memento)
    assert restored.items[0].dose_units == plan.items[0].dose_units
    assert later.items[0].dose_units != restored.items[0].dose_units


def test_the_caretaker_does_not_change_the_plan_it_photographs() -> None:
    snapshots = FakeSnapshots()
    plan = draft(*plan_items(insulin()))
    before = plan

    PlanSnapshotCaretaker(snapshots).before_change(plan, taken_by=DOCTOR, at=AT)

    assert plan == before
