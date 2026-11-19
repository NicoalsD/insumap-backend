"""P21 Visitor: every kind of event reaches its own method in every visitor."""

from dataclasses import replace
from datetime import timedelta
from typing import override

import pytest

from insumap.domain.monitoring.clinical_event import ClinicalEventVisitor
from insumap.domain.monitoring.glucose import GlucoseReading
from insumap.domain.monitoring.record import EntryType, RecordLifecycle
from insumap.domain.monitoring.records import (
    InsulinDose,
    Meal,
    PhysicalActivity,
    Symptom,
)
from insumap.domain.monitoring.timeline import (
    TimelineEventType,
    TimelineVisitor,
    build_timeline,
)
from tests.support.monitoring_factories import (
    NOW,
    make_activity,
    make_dose,
    make_meal,
    make_reading,
    make_symptom,
)


class CountingVisitor(ClinicalEventVisitor[str]):
    @override
    def visit_glucose_reading(self, event: GlucoseReading) -> str:
        return "glucose"

    @override
    def visit_insulin_dose(self, event: InsulinDose) -> str:
        return "insulin"

    @override
    def visit_meal(self, event: Meal) -> str:
        return "meal"

    @override
    def visit_physical_activity(self, event: PhysicalActivity) -> str:
        return "activity"

    @override
    def visit_symptom(self, event: Symptom) -> str:
        return "symptom"


def test_each_event_goes_to_its_own_method() -> None:
    visitor = CountingVisitor()

    names = [
        make_reading().accept(visitor),
        make_dose().accept(visitor),
        make_meal().accept(visitor),
        make_activity().accept(visitor),
        make_symptom().accept(visitor),
    ]

    assert names == ["glucose", "insulin", "meal", "activity", "symptom"]


def test_a_visitor_missing_a_method_cannot_be_instantiated() -> None:
    class Incomplete(ClinicalEventVisitor[str]):
        @override
        def visit_glucose_reading(self, event: GlucoseReading) -> str:
            return "glucose"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_the_timeline_visitor_gives_each_type_its_data() -> None:
    visitor = TimelineVisitor()

    kind, data = make_reading(mg_dl="95").accept(visitor)

    assert kind is TimelineEventType.GLUCOSE
    assert data["value_mg_dl"] == 95.0
    assert make_dose().accept(visitor)[0] is TimelineEventType.INSULIN
    assert make_meal().accept(visitor)[1]["carbs_g"] == 45.0
    assert make_activity().accept(visitor)[1]["duration_min"] == 30
    assert make_symptom().accept(visitor)[1]["is_alarm"] is False


def test_the_timeline_is_newest_first_and_hides_annulment_rows() -> None:
    older = make_reading(1, at=NOW - timedelta(hours=2))
    newer = make_meal(3)
    voided = replace(make_reading(2), entry_type=EntryType.VOID)

    items = build_timeline([older, voided, newer])

    assert [item.event_type for item in items] == [
        TimelineEventType.MEAL,
        TimelineEventType.GLUCOSE,
    ]


def test_a_superseded_record_shows_its_lifecycle_as_status() -> None:
    corrected = replace(make_reading(), lifecycle=RecordLifecycle.CORRECTED)

    assert build_timeline([corrected])[0].status == "CORRECTED"
    assert build_timeline([make_meal()])[0].status == "ACTIVE"
    assert build_timeline([make_reading()])[0].status == "ACCEPTED"
