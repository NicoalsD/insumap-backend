"""The timeline view of the clinical events, built with a visitor (P21)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import final, override
from uuid import UUID

from insumap.domain.monitoring.clinical_event import ClinicalEventVisitor
from insumap.domain.monitoring.glucose import GlucoseReading
from insumap.domain.monitoring.record import EntryType, TimelineRecord
from insumap.domain.monitoring.records import (
    InsulinDose,
    Meal,
    PhysicalActivity,
    Symptom,
)


class TimelineEventType(StrEnum):
    """The ``event_type`` of a timeline item and of its filter."""

    GLUCOSE = "GLUCOSE"
    INSULIN = "INSULIN"
    MEAL = "MEAL"
    ACTIVITY = "ACTIVITY"
    SYMPTOM = "SYMPTOM"


type TimelineData = Mapping[str, str | int | float | bool | None]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class TimelineItem:
    """One event of the timeline with the data proper to its type."""

    id: UUID
    event_type: TimelineEventType
    occurred_at: datetime
    status: str
    entry_type: EntryType
    data: TimelineData


@final
class TimelineVisitor(ClinicalEventVisitor[tuple[TimelineEventType, TimelineData]]):
    """Gives each event its type and its own data (no free text notes)."""

    @override
    def visit_glucose_reading(
        self, event: GlucoseReading
    ) -> tuple[TimelineEventType, TimelineData]:
        return TimelineEventType.GLUCOSE, {
            "value_mg_dl": float(event.value_mg_dl),
            "source": event.source.value,
            "context": None if event.context is None else event.context.value,
            "issue_codes": ",".join(code.value for code in event.issues),
        }

    @override
    def visit_insulin_dose(
        self, event: InsulinDose
    ) -> tuple[TimelineEventType, TimelineData]:
        return TimelineEventType.INSULIN, {
            "insulin_kind": event.insulin_kind.value,
            "product_name": event.product_name,
            "units": float(event.units),
        }

    @override
    def visit_meal(self, event: Meal) -> tuple[TimelineEventType, TimelineData]:
        return TimelineEventType.MEAL, {
            "meal_type": event.meal_type.value,
            "carbs_g": float(event.carbs_g),
        }

    @override
    def visit_physical_activity(
        self, event: PhysicalActivity
    ) -> tuple[TimelineEventType, TimelineData]:
        return TimelineEventType.ACTIVITY, {
            "activity_type": event.activity_type,
            "intensity": event.intensity.value,
            "duration_min": event.duration_min,
        }

    @override
    def visit_symptom(self, event: Symptom) -> tuple[TimelineEventType, TimelineData]:
        return TimelineEventType.SYMPTOM, {
            "symptom_code": event.symptom.code,
            "is_alarm": event.symptom.is_alarm,
        }


def build_timeline(records: Sequence[TimelineRecord]) -> tuple[TimelineItem, ...]:
    """The records as timeline items, newest first; annulment rows are not shown."""
    visitor = TimelineVisitor()
    items: list[TimelineItem] = []
    for record in records:
        if record.entry_type is EntryType.VOID:
            continue
        event_type, data = record.accept(visitor)
        items.append(
            TimelineItem(
                id=record.id,
                event_type=event_type,
                occurred_at=record.occurred_at,
                status=record.display_status,
                entry_type=record.entry_type,
                data=data,
            )
        )
    return tuple(
        sorted(items, key=lambda item: (item.occurred_at, item.id), reverse=True)
    )
