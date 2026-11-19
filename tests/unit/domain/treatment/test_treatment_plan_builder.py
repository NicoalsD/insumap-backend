"""P04 Builder: TreatmentPlanBuilder checks every invariant in build()."""

from dataclasses import replace
from decimal import Decimal

import pytest

from insumap.domain.treatment.builder import (
    PlanViolation,
    TreatmentPlanBuilder,
    TreatmentPlanInvariantError,
)
from insumap.domain.treatment.content import (
    InsulinKind,
    ItemSpec,
    ItemType,
    ProtocolLimits,
    TitrationRules,
)
from insumap.domain.treatment.plan import PlanStatus, TreatmentPlan
from insumap.shared.errors import ErrorCode
from tests.unit.domain.treatment.factories import (
    AT,
    draft,
    insulin,
    measure,
    plan_items,
)

LIMITS = ProtocolLimits(max_dose_units=Decimal("20"), min_gap_minutes=60)


def violations_of(
    plan: TreatmentPlan, limits: ProtocolLimits | None = None
) -> tuple[PlanViolation, ...]:
    with pytest.raises(TreatmentPlanInvariantError) as raised:
        TreatmentPlanBuilder(plan, limits=limits).build()
    assert raised.value.code is ErrorCode.VALIDATION_ERROR
    return raised.value.violations


def test_a_valid_draft_is_returned_unchanged_and_still_a_draft() -> None:
    plan = draft(*plan_items(insulin(), measure()))

    built = TreatmentPlanBuilder(plan, limits=LIMITS).build()

    assert built == plan
    assert built.status is PlanStatus.DRAFT


def test_an_empty_plan_is_refused() -> None:
    assert violations_of(draft()) == (PlanViolation("items", "empty_plan"),)


def test_insulin_needs_a_kind_and_a_dose_and_other_items_take_neither() -> None:
    bad_insulin = ItemSpec(item_type=ItemType.INSULIN, name="Sin tipo")
    bad_measure = ItemSpec(
        item_type=ItemType.MEASURE,
        name="Con tipo",
        insulin_kind=InsulinKind.BOLUS,
        dose_units=None,
    )

    found = violations_of(draft(*plan_items(bad_insulin, bad_measure)))

    assert found == (
        PlanViolation("items[0].insulin_kind", "insulin_required"),
        PlanViolation("items[0].dose_units", "dose_required"),
        PlanViolation("items[1].insulin_kind", "insulin_not_allowed"),
    )


def test_a_dose_must_be_positive_and_within_the_protocol_limit() -> None:
    zero = insulin("A", units="0", at="08:00")
    above = insulin("B", units="21", at="09:00")

    found = violations_of(draft(*plan_items(zero, above)), LIMITS)

    assert found == (
        PlanViolation("items[0].dose_units", "dose_not_positive"),
        PlanViolation("items[1].dose_units", "dose_above_limit"),
    )


def test_without_protocol_limits_only_the_structure_is_checked() -> None:
    plan = draft(*plan_items(insulin(units="500")))

    assert TreatmentPlanBuilder(plan).build() == plan


def test_two_items_at_the_same_time_on_a_shared_day_overlap() -> None:
    first = insulin("A", at="08:00", days=(1, 2))
    second = insulin("B", at="08:00", days=(2, 3))

    found = violations_of(draft(*plan_items(first, second)))

    assert found == (PlanViolation("items[1].time_of_day", "schedule_overlap"),)


def test_items_on_days_that_never_meet_do_not_overlap() -> None:
    weekdays = insulin("A", at="08:00", days=(1, 2, 3, 4, 5))
    weekend = insulin("B", at="08:00", days=(6, 7))

    assert TreatmentPlanBuilder(draft(*plan_items(weekdays, weekend))).build()


def test_a_missing_day_means_every_day_and_so_overlaps() -> None:
    every_day = insulin("A", at="08:00", days=None)
    weekend = insulin("B", at="08:00", days=(6, 7))

    found = violations_of(draft(*plan_items(every_day, weekend)))

    assert found == (PlanViolation("items[1].time_of_day", "schedule_overlap"),)


def test_items_closer_than_the_minimum_gap_are_too_close() -> None:
    first = insulin("A", at="08:00")
    second = insulin("B", at="08:30")

    found = violations_of(draft(*plan_items(first, second)), LIMITS)

    assert found == (PlanViolation("items[1].time_of_day", "schedule_too_close"),)


def test_invalid_days_are_refused() -> None:
    repeated = insulin("A", days=(1, 1))
    out_of_week = insulin("B", days=(8,))

    found = violations_of(draft(*plan_items(repeated, out_of_week)))

    assert found == (
        PlanViolation("items[0].days_of_week", "days_invalid"),
        PlanViolation("items[1].days_of_week", "days_invalid"),
    )


def test_incoherent_titration_rules_are_refused_all_at_once() -> None:
    plan = replace(
        draft(*plan_items(insulin())),
        titration_rules=TitrationRules(
            step_units=Decimal("0"),
            max_change_units=Decimal("0"),
            min_days_between_adjustments=-1,
        ),
    )

    found = violations_of(plan)

    assert found == (
        PlanViolation("titration_rules.step_units", "not_positive"),
        PlanViolation("titration_rules.min_days_between_adjustments", "negative"),
    )


def test_every_violation_is_reported_together() -> None:
    found = violations_of(
        draft(
            *plan_items(
                insulin("A", units="0", at="08:00"),
                insulin("B", units="5", at="08:00"),
                ItemSpec(item_type=ItemType.INSULIN, name="C", dose_units=Decimal("1")),
            ),
        ),
        LIMITS,
    )

    assert {violation.type for violation in found} >= {
        "dose_not_positive",
        "schedule_overlap",
        "insulin_required",
    }
    assert len(found) == 3


def test_the_error_lists_each_violation_as_field_and_type() -> None:
    with pytest.raises(TreatmentPlanInvariantError) as raised:
        TreatmentPlanBuilder(draft()).build()

    assert raised.value.detail == {
        "errors": [{"field": "items", "type": "empty_plan"}],
    }
    assert raised.value.code is ErrorCode.VALIDATION_ERROR


def test_the_builder_does_not_mutate_the_draft() -> None:
    plan = draft(*plan_items(insulin(units="0")))
    before = plan.items

    with pytest.raises(TreatmentPlanInvariantError):
        TreatmentPlanBuilder(plan, limits=LIMITS).build()

    assert plan.items == before
    assert plan.created_at == AT
