"""Plain values for the treatment domain tests (no protocol values are real)."""

from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID

from insumap.domain.treatment.content import (
    InsulinKind,
    ItemSpec,
    ItemType,
    PlanItem,
    TemplateContent,
    TitrationRules,
)
from insumap.domain.treatment.plan import TreatmentPlan

AT = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
CLINIC = UUID(int=1)
PATIENT = UUID(int=2)
DOCTOR = UUID(int=3)
TARGET = UUID(int=4)
PLAN = UUID(int=10)
TEMPLATE = UUID(int=20)


def uid(n: int) -> UUID:
    return UUID(int=1000 + n)


def insulin(
    name: str = "Basal", *, at: str | None = "08:00", units: str = "10", days=None
) -> ItemSpec:
    return ItemSpec(
        item_type=ItemType.INSULIN,
        name=name,
        insulin_kind=InsulinKind.BASAL,
        dose_units=Decimal(units),
        time_of_day=None if at is None else time.fromisoformat(at),
        days_of_week=days,
    )


def measure(at: str = "07:00") -> ItemSpec:
    return ItemSpec(
        item_type=ItemType.MEASURE,
        name="Glucometría",
        time_of_day=time.fromisoformat(at),
    )


def rules() -> TitrationRules:
    return TitrationRules(
        step_units=Decimal("1"),
        max_change_units=Decimal("4"),
        min_days_between_adjustments=3,
    )


def draft(*items: PlanItem, notes: str | None = None) -> TreatmentPlan:
    return TreatmentPlan.draft(
        plan_id=PLAN,
        clinic_id=CLINIC,
        patient_id=PATIENT,
        version=1,
        target_profile_id=TARGET,
        created_by=DOCTOR,
        at=AT,
        items=tuple(items),
        titration_rules=rules(),
        notes=notes,
    )


def plan_items(*specs: ItemSpec) -> tuple[PlanItem, ...]:
    return tuple(PlanItem.of(uid(index), spec) for index, spec in enumerate(specs))


def template_content(*specs: ItemSpec) -> TemplateContent:
    return TemplateContent(items=tuple(specs), titration_rules=rules())
