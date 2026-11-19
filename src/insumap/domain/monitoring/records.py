"""Insulin doses, meals, physical activities, symptoms and lab results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, final, override
from uuid import UUID

from insumap.domain.common.rounding import round_half_up
from insumap.domain.monitoring.injection_sites import SPOT_MAX, SPOT_MIN, SiteCode
from insumap.domain.monitoring.record import ClinicalRecord, TimelineRecord
from insumap.shared.units import NGSP_PERCENT_INTERCEPT, NGSP_PERCENT_PER_IFCC

if TYPE_CHECKING:
    from insumap.domain.monitoring.clinical_event import ClinicalEventVisitor

HBA1C_DECIMALS = 1


class InsulinKind(StrEnum):
    BASAL = "BASAL"
    BOLUS = "BOLUS"
    CORRECTION = "CORRECTION"
    MIXED = "MIXED"


class MealType(StrEnum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"
    SNACK = "SNACK"


class ActivityIntensity(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class LabUnit(StrEnum):
    PERCENT = "%"
    MMOL_PER_MOL = "mmol/mol"


class LabOrigin(StrEnum):
    PATIENT_REPORTED = "PATIENT_REPORTED"
    LAB = "LAB"


def hba1c_to_percent(value: Decimal, unit: LabUnit) -> Decimal:
    """HbA1c in NGSP percent; mmol/mol uses the IFCC-NGSP master equation."""
    percent = (
        value
        if unit is LabUnit.PERCENT
        else NGSP_PERCENT_PER_IFCC * value + NGSP_PERCENT_INTERCEPT
    )
    return round_half_up(percent, HBA1C_DECIMALS)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InsulinDose(TimelineRecord):
    """A dose the patient says they took. The API never computes or suggests one."""

    administered_at: datetime
    insulin_kind: InsulinKind
    product_name: str
    units: Decimal
    plan_id: UUID | None = None
    note: str | None = None
    injection_site: SiteCode | None = None
    injection_spot: int | None = None

    def __post_init__(self) -> None:
        if self.injection_spot is None:
            return
        if self.injection_site is None:
            raise ValueError("an injection spot needs an injection site")
        if not SPOT_MIN <= self.injection_spot <= SPOT_MAX:
            raise ValueError("the injection spot is outside the catalog")

    @property
    @override
    def occurred_at(self) -> datetime:
        return self.administered_at

    @override
    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_insulin_dose(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Meal(TimelineRecord):
    """A meal with estimated carbohydrates."""

    eaten_at: datetime
    meal_type: MealType
    carbs_g: Decimal
    note: str | None = None

    @property
    @override
    def occurred_at(self) -> datetime:
        return self.eaten_at

    @override
    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_meal(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PhysicalActivity(TimelineRecord):
    """A physical activity, used as context in the patterns."""

    started_at: datetime
    activity_type: str
    duration_min: int
    intensity: ActivityIntensity
    note: str | None = None

    @property
    @override
    def occurred_at(self) -> datetime:
        return self.started_at

    @override
    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_physical_activity(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SymptomEntry:
    """The catalog entry a symptom row points at."""

    symptom_id: UUID
    code: str
    is_alarm: bool


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Symptom(TimelineRecord):
    """A symptom picked from the clinic catalog."""

    symptom_at: datetime
    symptom: SymptomEntry
    note: str | None = None

    @property
    @override
    def occurred_at(self) -> datetime:
        return self.symptom_at

    @override
    def accept[R](self, visitor: ClinicalEventVisitor[R]) -> R:
        return visitor.visit_symptom(self)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class LabResult(ClinicalRecord):
    """An HbA1c result: self reported or confirmed by the doctor."""

    test_code: str
    performed_on: date
    value: Decimal
    unit: LabUnit
    value_pct: Decimal
    origin: LabOrigin

    @property
    @override
    def occurred_at(self) -> datetime:
        """The exam date as midnight UTC, only to order the listing."""
        return datetime.combine(self.performed_on, time.min, tzinfo=UTC)
