"""What a person typed, already parsed: the values of a record before it exists."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from insumap.domain.monitoring.glucose import GlucoseUnit, ReadingContext, ReadingSource
from insumap.domain.monitoring.injection_sites import SiteCode
from insumap.domain.monitoring.records import (
    ActivityIntensity,
    InsulinKind,
    LabOrigin,
    LabUnit,
    MealType,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseData:
    value: Decimal
    unit: GlucoseUnit
    measured_at: datetime
    source: ReadingSource
    context: ReadingContext | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class InsulinData:
    administered_at: datetime
    insulin_kind: InsulinKind
    product_name: str
    units: Decimal
    note: str | None = None
    injection_site: SiteCode | None = None
    injection_spot: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MealData:
    eaten_at: datetime
    meal_type: MealType
    carbs_g: Decimal
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityData:
    started_at: datetime
    activity_type: str
    duration_min: int
    intensity: ActivityIntensity
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SymptomData:
    symptom_code: str
    occurred_at: datetime
    note: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class LabData:
    value: Decimal
    unit: LabUnit
    performed_on: date
    origin: LabOrigin = LabOrigin.PATIENT_REPORTED


type RecordData = GlucoseData | InsulinData | MealData | ActivityData | SymptomData
