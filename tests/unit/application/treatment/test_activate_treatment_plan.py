"""P13 Command: ActivateTreatmentPlanCommand, behind the audit decorator (P09)."""

from dataclasses import replace
from uuid import UUID

import pytest

from insumap.application.common.actor import Actor
from insumap.application.treatment.plan_commands import ActivateTreatmentPlanCommand
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.treatment.builder import TreatmentPlanInvariantError
from insumap.domain.treatment.content import ItemSpec
from insumap.domain.treatment.plan import PlanStatus, TreatmentPlan
from insumap.shared.errors import ErrorCode
from tests.support.treatment_fakes import active
from tests.unit.application.treatment.helpers import (
    World,
    doctor,
    limited,
    template_row,
)
from tests.unit.domain.treatment.factories import (
    DOCTOR,
    PATIENT,
    PLAN,
    TEMPLATE,
    draft,
    insulin,
    measure,
    plan_items,
)

OLD_PLAN = UUID(int=11)


def a_draft(
    plan_id: UUID = PLAN, *, version: int = 2, items: tuple[ItemSpec, ...] | None = None
) -> TreatmentPlan:
    specs = (insulin(), measure()) if items is None else items
    base = draft(*plan_items(*specs))
    return replace(base, plan_id=plan_id, version=version)


def an_active(plan_id: UUID = OLD_PLAN) -> TreatmentPlan:
    return active(replace(a_draft(plan_id, version=1), status=PlanStatus.ACTIVE))


def activate(world: World, plan_id: UUID, actor: Actor | None = None) -> TreatmentPlan:
    return world.activate.handle(
        ActivateTreatmentPlanCommand(actor=actor or doctor(), plan_id=plan_id)
    )


def test_activation_supersedes_the_active_plan_before_activating_the_draft() -> None:
    world = World(plans=(an_active(), a_draft()))

    activated = activate(world, PLAN)

    assert activated.status is PlanStatus.ACTIVE
    assert activated.activated_by == DOCTOR
    assert world.plans.rows[OLD_PLAN].status is PlanStatus.SUPERSEDED
    assert world.plans.writes == ["update:SUPERSEDED", "update:ACTIVE"]


def test_both_photos_are_taken_before_their_plans_change() -> None:
    world = World(plans=(an_active(), a_draft()))

    activate(world, PLAN)

    photographed = [row.plan_id for row in world.snapshots.rows]
    assert photographed == [OLD_PLAN, PLAN]
    superseded_photo = world.snapshots.rows[0].memento.data
    assert superseded_photo["status"] == "ACTIVE"


def test_a_plan_without_a_previous_active_one_just_activates() -> None:
    world = World(plans=(a_draft(),))

    activate(world, PLAN)

    assert world.plans.writes == ["update:ACTIVE"]
    assert [row.plan_id for row in world.snapshots.rows] == [PLAN]


def test_an_invalid_draft_is_refused_and_nothing_is_written() -> None:
    world = World(plans=(an_active(), a_draft(items=())))

    with pytest.raises(TreatmentPlanInvariantError) as raised:
        activate(world, PLAN)

    assert raised.value.code is ErrorCode.VALIDATION_ERROR
    assert raised.value.detail == {"errors": [{"field": "items", "type": "empty_plan"}]}
    assert world.plans.writes == []
    assert world.snapshots.rows == []
    assert world.plans.rows[OLD_PLAN].status is PlanStatus.ACTIVE


def test_only_a_draft_can_be_activated() -> None:
    world = World(plans=(an_active(),))

    with pytest.raises(InvalidStateTransitionError):
        activate(world, OLD_PLAN)
    assert world.plans.writes == []


def test_the_limits_of_the_template_the_plan_came_from_apply() -> None:
    template = template_row(content=limited("20"))
    plan = replace(a_draft(items=(insulin(units="25"),)), template_id=TEMPLATE)
    world = World(plans=(plan,), templates=(template,))

    with pytest.raises(TreatmentPlanInvariantError) as raised:
        activate(world, PLAN)

    assert raised.value.detail == {
        "errors": [{"field": "items[0].dose_units", "type": "dose_above_limit"}]
    }


def test_an_unassigned_patient_is_not_found_and_nothing_is_read_or_written() -> None:
    world = World(plans=(a_draft(),), assigned=())

    with pytest.raises(ResourceNotFoundError):
        activate(world, PLAN)

    assert world.plans.writes == []
    assert world.snapshots.rows == []


def test_a_user_without_the_permission_is_refused_first() -> None:
    world = World(plans=(a_draft(),))

    with pytest.raises(PermissionDeniedError):
        activate(world, PLAN, actor=doctor(permissions=frozenset()))


def test_another_doctor_of_the_patient_is_not_assigned_to_it() -> None:
    world = World(plans=(a_draft(),), assigned=((DOCTOR, PATIENT),))

    with pytest.raises(ResourceNotFoundError):
        activate(world, PLAN, actor=doctor(user=UUID(int=77)))


def test_the_bus_audits_the_activation_with_field_names_only() -> None:
    world = World(plans=(an_active(), a_draft()))

    activated = world.bus().dispatch(
        ActivateTreatmentPlanCommand(actor=doctor(), plan_id=PLAN)
    )

    assert activated.status is PlanStatus.ACTIVE
    (entry,) = world.audit.entries
    assert entry.action == "TREATMENT_PLAN_ACTIVATED"
    assert entry.entity_type == "TREATMENT_PLAN"
    assert entry.entity_id == PLAN
    assert "status" in entry.changed_fields
    assert "ACTIVE" not in str(entry)
