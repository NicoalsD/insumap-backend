"""P05 Prototype: TreatmentPlan.copy_for_new_version() and the lifecycle of a plan."""

from datetime import timedelta
from uuid import UUID

import pytest

from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.treatment.plan import PlanStatus, TreatmentPlan
from tests.unit.domain.treatment.factories import (
    AT,
    DOCTOR,
    LATER,
    PLAN,
    draft,
    insulin,
    measure,
    plan_items,
    uid,
)

NEW_PLAN = UUID(int=700)


def active_plan() -> TreatmentPlan:
    plan = draft(*plan_items(insulin(), measure()))
    return plan.activate(by=DOCTOR, at=AT)


def test_a_new_version_is_a_draft_with_the_next_version_and_new_ids() -> None:
    source = active_plan()

    copy = source.open_new_version(
        new_plan_id=NEW_PLAN,
        item_ids=(uid(50), uid(51)),
        version=2,
        created_by=DOCTOR,
        at=LATER,
    )

    assert copy.status is PlanStatus.DRAFT
    assert copy.plan_id == NEW_PLAN
    assert copy.version == 2
    assert copy.previous_plan_id == PLAN
    assert [item.item_id for item in copy.items] == [uid(50), uid(51)]
    assert [item.name for item in copy.items] == [i.name for i in source.items]
    assert copy.created_at == LATER


def test_the_active_plan_is_left_exactly_as_it_was() -> None:
    source = active_plan()
    before = (source.status, source.items, source.version)

    source.open_new_version(
        new_plan_id=NEW_PLAN,
        item_ids=(uid(50), uid(51)),
        version=2,
        created_by=DOCTOR,
        at=LATER,
    )

    assert (source.status, source.items, source.version) == before


def test_only_an_active_plan_opens_a_new_version() -> None:
    draft_plan = draft(*plan_items(insulin()))

    with pytest.raises(InvalidStateTransitionError):
        draft_plan.open_new_version(
            new_plan_id=NEW_PLAN,
            item_ids=(uid(50),),
            version=2,
            created_by=DOCTOR,
            at=LATER,
        )


def test_the_copy_needs_one_identifier_per_item() -> None:
    with pytest.raises(ValueError, match="one new identifier per item"):
        active_plan().copy_for_new_version(
            new_plan_id=NEW_PLAN,
            item_ids=(uid(50),),
            version=2,
            created_by=DOCTOR,
            at=LATER,
        )


def test_activation_moves_a_draft_to_active_with_its_actor_and_instant() -> None:
    plan = draft(*plan_items(insulin()))

    active = plan.activate(by=DOCTOR, at=LATER)

    assert active.status is PlanStatus.ACTIVE
    assert active.activated_by == DOCTOR
    assert active.activated_at == LATER
    assert active.lock_version == plan.lock_version + 1


def test_a_plan_is_superseded_only_once_and_only_when_active() -> None:
    active = active_plan()
    superseded = active.supersede(at=LATER)

    assert superseded.status is PlanStatus.SUPERSEDED
    assert superseded.superseded_at == LATER
    with pytest.raises(InvalidStateTransitionError):
        superseded.supersede(at=LATER + timedelta(minutes=1))
    with pytest.raises(InvalidStateTransitionError):
        draft(*plan_items(insulin())).supersede(at=LATER)


def test_an_active_plan_is_not_edited_in_place() -> None:
    with pytest.raises(InvalidStateTransitionError):
        active_plan().with_content(
            items=(), titration_rules=None, notes="cambio", at=LATER
        )


def test_a_draft_content_can_be_replaced_and_bumps_the_lock() -> None:
    plan = draft(*plan_items(insulin()))

    edited = plan.with_content(
        items=plan_items(measure()), titration_rules=None, notes="ajuste", at=LATER
    )

    assert [item.name for item in edited.items] == ["Glucometría"]
    assert edited.notes == "ajuste"
    assert edited.updated_at == LATER
    assert edited.lock_version == 1
