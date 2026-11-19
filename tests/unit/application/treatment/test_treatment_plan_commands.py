"""Plan decisions: create, edit a draft, open a version, restore a photo."""

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from insumap.application.treatment.inputs import PlanContentInput
from insumap.application.treatment.plan_commands import (
    CreateTreatmentPlanCommand,
    CreateTreatmentPlanVersionCommand,
    RestoreTreatmentPlanCommand,
    UpdateTreatmentPlanCommand,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.treatment.plan import PlanStatus
from insumap.domain.treatment.template import TemplateStatus
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.treatment_fakes import active
from tests.unit.application.treatment.helpers import (
    World,
    doctor,
    template_row,
)
from tests.unit.domain.treatment.factories import (
    DOCTOR,
    PATIENT,
    PLAN,
    TARGET,
    TEMPLATE,
    draft,
    insulin,
    measure,
    plan_items,
)

OTHER_TARGET = UUID(int=44)
NEW = PlanContentInput(items=(insulin("Nueva", units="4"),), notes="Ajuste")


def a_draft(plan_id: UUID = PLAN, version: int = 1):
    return replace(
        draft(*plan_items(insulin(), measure())), plan_id=plan_id, version=version
    )


def an_active(plan_id: UUID = PLAN, version: int = 1):
    return active(a_draft(plan_id, version))


# Create.


def test_a_plan_from_a_template_is_a_draft_cloned_with_the_template_profile() -> None:
    template = template_row(default_profile=OTHER_TARGET)
    world = World(templates=(template,))

    plan = world.create_plan.handle(
        CreateTreatmentPlanCommand(
            actor=doctor(), patient_id=PATIENT, template_id=TEMPLATE
        )
    )

    assert plan.status is PlanStatus.DRAFT
    assert plan.template_id == TEMPLATE
    assert plan.version == 1
    assert plan.target_profile_id == OTHER_TARGET
    assert [item.name for item in plan.items] == ["Basal", "Glucometría"]
    assert all(item.item_id not in {UUID(int=0)} for item in plan.items)
    assert world.plans.writes == ["insert:1:DRAFT"]


def test_without_a_template_the_patient_profile_is_used() -> None:
    world = World()

    plan = world.create_plan.handle(
        CreateTreatmentPlanCommand(actor=doctor(), patient_id=PATIENT, content=NEW)
    )

    assert plan.target_profile_id == TARGET
    assert plan.notes == "Ajuste"
    assert [item.name for item in plan.items] == ["Nueva"]


def test_a_template_can_be_personalised_at_creation() -> None:
    world = World(templates=(template_row(),))

    plan = world.create_plan.handle(
        CreateTreatmentPlanCommand(
            actor=doctor(), patient_id=PATIENT, template_id=TEMPLATE, content=NEW
        )
    )

    assert [item.name for item in plan.items] == ["Nueva"]
    assert plan.template_id == TEMPLATE


def test_the_next_version_follows_the_highest_one_of_the_patient() -> None:
    world = World(plans=(an_active(version=3),))

    plan = world.create_plan.handle(
        CreateTreatmentPlanCommand(actor=doctor(), patient_id=PATIENT, content=NEW)
    )

    assert plan.version == 4


def test_a_retired_template_cannot_start_a_plan() -> None:
    world = World(templates=(template_row(status=TemplateStatus.RETIRED),))

    with pytest.raises(InvalidStateTransitionError):
        world.create_plan.handle(
            CreateTreatmentPlanCommand(
                actor=doctor(), patient_id=PATIENT, template_id=TEMPLATE
            )
        )


def test_a_missing_template_is_not_found() -> None:
    world = World()

    with pytest.raises(ResourceNotFoundError):
        world.create_plan.handle(
            CreateTreatmentPlanCommand(
                actor=doctor(), patient_id=PATIENT, template_id=TEMPLATE
            )
        )


def test_a_clinic_without_goals_is_a_setup_error_not_a_user_error() -> None:
    world = World(target=None)

    with pytest.raises(InsumapError) as raised:
        world.create_plan.handle(
            CreateTreatmentPlanCommand(actor=doctor(), patient_id=PATIENT, content=NEW)
        )

    assert raised.value.code is ErrorCode.INTERNAL_ERROR


def test_an_unassigned_patient_is_not_found_before_any_write() -> None:
    world = World(assigned=())

    with pytest.raises(ResourceNotFoundError):
        world.create_plan.handle(
            CreateTreatmentPlanCommand(actor=doctor(), patient_id=PATIENT, content=NEW)
        )
    assert world.plans.writes == []


# Edit a draft.


def test_editing_a_draft_takes_a_photo_of_the_old_content_first() -> None:
    world = World(plans=(a_draft(),))

    edited = world.update_plan.handle(
        UpdateTreatmentPlanCommand(actor=doctor(), plan_id=PLAN, content=NEW)
    )

    assert [item.name for item in edited.items] == ["Nueva"]
    (photo,) = world.snapshots.rows
    assert photo.plan_id == PLAN
    assert [item["name"] for item in photo.memento.data["items"]] == [
        "Basal",
        "Glucometría",
    ]
    assert world.plans.writes == ["update:DRAFT", "items"]


def test_an_active_plan_is_never_edited_and_nothing_is_photographed() -> None:
    world = World(plans=(an_active(),))

    with pytest.raises(InvalidStateTransitionError):
        world.update_plan.handle(
            UpdateTreatmentPlanCommand(actor=doctor(), plan_id=PLAN, content=NEW)
        )
    assert world.snapshots.rows == []
    assert world.plans.writes == []


# Versions.


def test_a_new_version_is_a_draft_copy_and_the_active_plan_stays_active() -> None:
    world = World(plans=(an_active(),))

    version = world.new_version.handle(
        CreateTreatmentPlanVersionCommand(actor=doctor(), plan_id=PLAN)
    )

    assert version.status is PlanStatus.DRAFT
    assert version.version == 2
    assert version.previous_plan_id == PLAN
    assert world.plans.rows[PLAN].status is PlanStatus.ACTIVE
    original_ids = {item.item_id for item in world.plans.rows[PLAN].items}
    assert not original_ids & {item.item_id for item in version.items}


def test_only_an_active_plan_opens_a_version() -> None:
    world = World(plans=(a_draft(),))

    with pytest.raises(InvalidStateTransitionError):
        world.new_version.handle(
            CreateTreatmentPlanVersionCommand(actor=doctor(), plan_id=PLAN)
        )


# Restore.


def test_restoring_a_photo_creates_a_new_draft_and_keeps_the_history() -> None:
    world = World(plans=(a_draft(),))
    world.update_plan.handle(
        UpdateTreatmentPlanCommand(actor=doctor(), plan_id=PLAN, content=NEW)
    )
    photo = world.snapshots.rows[0]

    restored = world.restore.handle(
        RestoreTreatmentPlanCommand(
            actor=doctor(), plan_id=PLAN, snapshot_id=photo.snapshot_id
        )
    )

    assert restored.status is PlanStatus.DRAFT
    assert restored.plan_id != PLAN
    assert restored.previous_plan_id == PLAN
    assert [item.name for item in restored.items] == ["Basal", "Glucometría"]
    assert restored.version == 2
    assert len(world.snapshots.rows) == 1


def test_a_photo_of_another_plan_is_not_found() -> None:
    world = World(plans=(a_draft(),))
    other = UUID(int=99)
    world.snapshots.append(
        plan_id=other,
        number=1,
        memento=a_draft(other).create_memento(taken_at=world.clock.now()),
        taken_by=DOCTOR,
    )
    photo = world.snapshots.rows[0]

    with pytest.raises(ResourceNotFoundError):
        world.restore.handle(
            RestoreTreatmentPlanCommand(
                actor=doctor(), plan_id=PLAN, snapshot_id=photo.snapshot_id
            )
        )


def test_the_restored_content_is_the_photo_content_not_the_current_one() -> None:
    world = World(plans=(a_draft(),))
    world.update_plan.handle(
        UpdateTreatmentPlanCommand(actor=doctor(), plan_id=PLAN, content=NEW)
    )
    photo = world.snapshots.rows[0]

    restored = world.restore.handle(
        RestoreTreatmentPlanCommand(
            actor=doctor(), plan_id=PLAN, snapshot_id=photo.snapshot_id
        )
    )

    assert Decimal("4") not in {item.dose_units for item in restored.items}
    assert restored.items[0].dose_units == Decimal("10")
