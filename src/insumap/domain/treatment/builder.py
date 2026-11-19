"""Validation of a treatment plan before it is activated (P04 Builder).

Drafts are not validated: a clinician can save an incomplete plan and come back
to it. ``TreatmentPlanBuilder.build()`` checks every invariant at once and
returns all the violations, never just the first one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Final, final

from insumap.domain.treatment.content import ItemSpec, ItemType, ProtocolLimits
from insumap.domain.treatment.plan import TreatmentPlan
from insumap.shared.errors import ErrorCode, InsumapError

FIRST_WEEKDAY: Final = 1
LAST_WEEKDAY: Final = 7
MINUTES_PER_HOUR: Final = 60
ZERO: Final = Decimal(0)


@final
@dataclass(frozen=True, slots=True)
class PlanViolation:
    """One broken invariant: where it is and what rule it breaks."""

    field: str
    type: str


@final
class TreatmentPlanInvariantError(InsumapError):
    """The plan breaks at least one invariant; each one is listed (``422``)."""

    def __init__(self, violations: Sequence[PlanViolation]) -> None:
        self.violations = tuple(violations)
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [
                    {"field": violation.field, "type": violation.type}
                    for violation in self.violations
                ]
            },
        )


@final
class TreatmentPlanBuilder:
    """Pattern: P04 Builder. Checks every invariant of a draft in ``build()``.

    The limits come from the protocol the plan was built from (a template's
    content); without them only the structural invariants apply.
    """

    def __init__(
        self, draft: TreatmentPlan, *, limits: ProtocolLimits | None = None
    ) -> None:
        self._draft = draft
        self._limits = limits or ProtocolLimits()

    def build(self) -> TreatmentPlan:
        """The draft, once every invariant holds; otherwise all violations at once."""
        violations = self._violations()
        if violations:
            raise TreatmentPlanInvariantError(violations)
        return self._draft

    def _violations(self) -> list[PlanViolation]:
        found: list[PlanViolation] = []
        if not self._draft.items:
            found.append(PlanViolation("items", "empty_plan"))
        for index, item in enumerate(self._draft.items):
            found.extend(self._item_violations(index, item))
        found.extend(self._schedule_violations())
        found.extend(self._rules_violations())
        return found

    def _item_violations(self, index: int, item: ItemSpec) -> list[PlanViolation]:
        path = f"items[{index}]"
        found: list[PlanViolation] = []
        if item.item_type is ItemType.INSULIN:
            if item.insulin_kind is None:
                found.append(PlanViolation(f"{path}.insulin_kind", "insulin_required"))
            if item.dose_units is None:
                found.append(PlanViolation(f"{path}.dose_units", "dose_required"))
        elif item.insulin_kind is not None:
            found.append(PlanViolation(f"{path}.insulin_kind", "insulin_not_allowed"))
        dose = item.dose_units
        if dose is not None:
            if dose <= ZERO:
                found.append(PlanViolation(f"{path}.dose_units", "dose_not_positive"))
            elif (
                self._limits.max_dose_units is not None
                and dose > self._limits.max_dose_units
            ):
                found.append(PlanViolation(f"{path}.dose_units", "dose_above_limit"))
        if item.days_of_week is not None and not _valid_days(item.days_of_week):
            found.append(PlanViolation(f"{path}.days_of_week", "days_invalid"))
        return found

    def _schedule_violations(self) -> list[PlanViolation]:
        timed = [
            (index, item.time_of_day, item)
            for index, item in enumerate(self._draft.items)
            if item.time_of_day is not None
        ]
        min_gap = self._limits.min_gap_minutes
        found: list[PlanViolation] = []
        for position, (later_index, later_time, later) in enumerate(timed):
            for _, earlier_time, earlier in timed[:position]:
                if not _share_a_day(earlier.days_of_week, later.days_of_week):
                    continue
                gap = abs(_minute_of_day(later_time) - _minute_of_day(earlier_time))
                path = f"items[{later_index}].time_of_day"
                if gap == 0:
                    found.append(PlanViolation(path, "schedule_overlap"))
                elif min_gap is not None and gap < min_gap:
                    found.append(PlanViolation(path, "schedule_too_close"))
        return found

    def _rules_violations(self) -> list[PlanViolation]:
        rules = self._draft.titration_rules
        if rules is None:
            return []
        found: list[PlanViolation] = []
        if rules.step_units <= ZERO:
            found.append(PlanViolation("titration_rules.step_units", "not_positive"))
        if rules.max_change_units < rules.step_units:
            found.append(
                PlanViolation("titration_rules.max_change_units", "below_step")
            )
        if rules.min_days_between_adjustments < 0:
            found.append(
                PlanViolation(
                    "titration_rules.min_days_between_adjustments", "negative"
                )
            )
        return found


def _valid_days(days: tuple[int, ...]) -> bool:
    in_week = all(FIRST_WEEKDAY <= day <= LAST_WEEKDAY for day in days)
    return in_week and len(set(days)) == len(days)


def _share_a_day(first: tuple[int, ...] | None, second: tuple[int, ...] | None) -> bool:
    """``None`` means every day, so it shares a day with any other item."""
    if first is None or second is None:
        return True
    return bool(set(first) & set(second))


def _minute_of_day(at: time | None) -> int:
    if at is None:
        raise ValueError("a time of day is required")
    return at.hour * MINUTES_PER_HOUR + at.minute
