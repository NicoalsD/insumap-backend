"""Builders of patient records for tests: ids and times are deterministic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from insumap.domain.monitoring.glucose import (
    GlucoseReading,
    GlucoseUnit,
    GlucoseValue,
    IssueCode,
    ReadingContext,
    ReadingSource,
)
from insumap.domain.monitoring.records import (
    ActivityIntensity,
    InsulinDose,
    InsulinKind,
    Meal,
    MealType,
    PhysicalActivity,
    Symptom,
    SymptomEntry,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC_ID = UUID(int=0xC1)
PATIENT_ID = UUID(int=0xA1)
USER_ID = UUID(int=0xB1)


def uid(number: int) -> UUID:
    return UUID(int=number)


def common(number: int, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": uid(number),
        "clinic_id": CLINIC_ID,
        "patient_id": PATIENT_ID,
        "client_record_id": uid(1000 + number),
        "recorded_by": USER_ID,
        "received_at": NOW,
    }
    return {**base, **overrides}


def make_reading(
    number: int = 1,
    *,
    mg_dl: str = "110",
    at: datetime = NOW,
    source: ReadingSource = ReadingSource.SMBG,
    context: ReadingContext | None = ReadingContext.FASTING,
    issues: tuple[IssueCode, ...] = (),
) -> GlucoseReading:
    return GlucoseReading.record(
        reading_id=uid(number),
        event_id=uid(2000 + number),
        clinic_id=CLINIC_ID,
        patient_id=PATIENT_ID,
        client_reading_id=uid(1000 + number),
        recorded_by=USER_ID,
        value=GlucoseValue.from_input(Decimal(mg_dl), GlucoseUnit.MG_DL),
        measured_at=at,
        source=source,
        context=context,
        note=None,
        issues=issues,
        now=NOW,
    )


def make_dose(number: int = 2, *, name: str = "Glargina") -> InsulinDose:
    return InsulinDose(
        **common(number),
        administered_at=NOW,
        insulin_kind=InsulinKind.BASAL,
        product_name=name,
        units=Decimal("12.5"),
    )


def make_meal(number: int = 3) -> Meal:
    return Meal(
        **common(number),
        eaten_at=NOW,
        meal_type=MealType.LUNCH,
        carbs_g=Decimal(45),
    )


def make_activity(number: int = 4, *, kind: str = "Caminata") -> PhysicalActivity:
    return PhysicalActivity(
        **common(number),
        started_at=NOW,
        activity_type=kind,
        duration_min=30,
        intensity=ActivityIntensity.MODERATE,
    )


def make_symptom(number: int = 5, *, code: str = "THIRST") -> Symptom:
    return Symptom(
        **common(number),
        symptom_at=NOW,
        symptom=SymptomEntry(symptom_id=uid(500), code=code, is_alarm=False),
    )
