"""The JSON export of a patient's own data (P21 Visitor over the clinical events)."""

from __future__ import annotations

from typing import Final, final, override

from insumap.domain.monitoring.clinical_event import ClinicalEvent, ClinicalEventVisitor
from insumap.domain.monitoring.glucose import GlucoseReading
from insumap.domain.monitoring.records import (
    InsulinDose,
    Meal,
    PhysicalActivity,
    Symptom,
)

JSON_MEDIA_TYPE: Final = "application/json; charset=utf-8"

type JsonObject = dict[str, object]


@final
class JsonEventVisitor(ClinicalEventVisitor[JsonObject]):
    """One JSON object per clinical event, without internal identifiers.

    Pattern: P21 Visitor
    """

    @override
    def visit_glucose_reading(self, event: GlucoseReading) -> JsonObject:
        return {
            "type": "GLUCOSE_READING",
            "occurred_at": event.measured_at.isoformat(),
            "value_mg_dl": str(event.value_mg_dl),
            "source": event.source.value,
            "context": None if event.context is None else event.context.value,
            "note": event.note,
        }

    @override
    def visit_insulin_dose(self, event: InsulinDose) -> JsonObject:
        return {
            "type": "INSULIN_DOSE",
            "occurred_at": event.administered_at.isoformat(),
            "insulin_kind": event.insulin_kind.value,
            "product_name": event.product_name,
            "units": str(event.units),
            "injection_site": None
            if event.injection_site is None
            else event.injection_site.value,
            "injection_spot": event.injection_spot,
            "note": event.note,
        }

    @override
    def visit_meal(self, event: Meal) -> JsonObject:
        return {
            "type": "MEAL",
            "occurred_at": event.eaten_at.isoformat(),
            "meal_type": event.meal_type.value,
            "carbs_g": str(event.carbs_g),
            "note": event.note,
        }

    @override
    def visit_physical_activity(self, event: PhysicalActivity) -> JsonObject:
        return {
            "type": "PHYSICAL_ACTIVITY",
            "occurred_at": event.started_at.isoformat(),
            "activity_type": event.activity_type,
            "duration_min": event.duration_min,
            "intensity": event.intensity.value,
            "note": event.note,
        }

    @override
    def visit_symptom(self, event: Symptom) -> JsonObject:
        return {
            "type": "SYMPTOM",
            "occurred_at": event.symptom_at.isoformat(),
            "code": event.symptom.code,
            "note": event.note,
        }


def events_as_json(events: list[ClinicalEvent]) -> list[JsonObject]:
    """Each event through the visitor, in the order given."""
    visitor = JsonEventVisitor()
    return [_accept(visitor, event) for event in events]


def _accept(visitor: JsonEventVisitor, event: ClinicalEvent) -> JsonObject:
    if isinstance(event, GlucoseReading):
        return visitor.visit_glucose_reading(event)
    if isinstance(event, InsulinDose):
        return visitor.visit_insulin_dose(event)
    if isinstance(event, Meal):
        return visitor.visit_meal(event)
    if isinstance(event, PhysicalActivity):
        return visitor.visit_physical_activity(event)
    return visitor.visit_symptom(event)
