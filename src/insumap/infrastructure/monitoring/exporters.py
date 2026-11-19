"""Timeline exports: CSV and FHIR, each one a visitor over the clinical events."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from typing import Final, final, override
from uuid import UUID

from insumap.application.monitoring.queries import ExportedFile, TimelineExporterPort
from insumap.domain.monitoring.clinical_event import (
    ClinicalEvent,
    ClinicalEventVisitor,
)
from insumap.domain.monitoring.glucose import GlucoseReading, ReadingSource
from insumap.domain.monitoring.records import (
    InsulinDose,
    Meal,
    PhysicalActivity,
    Symptom,
)

FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")
CSV_MEDIA_TYPE: Final = "text/csv; charset=utf-8"
FHIR_MEDIA_TYPE: Final = "application/fhir+json"
CSV_HEADER: Final = (
    "occurred_at",
    "event_type",
    "status",
    "entry_type",
    "value",
    "unit",
    "detail",
)
UCUM: Final = "http://unitsofmeasure.org"
LOINC: Final = "http://loinc.org"
INSUMAP_EVENT_SYSTEM: Final = (
    "https://insumap.example.test/fhir/CodeSystem/clinical-event"
)
INSUMAP_SYMPTOM_SYSTEM: Final = "https://insumap.example.test/fhir/CodeSystem/symptom"
LOINC_BY_SOURCE: Final = {
    ReadingSource.CGM: ("99504-3", "Glucose [Mass/volume] in Interstitial fluid"),
    ReadingSource.SMBG: (
        "41653-7",
        "Glucose [Mass/volume] in Capillary blood by Glucometer",
    ),
    ReadingSource.MANUAL: ("2339-0", "Glucose [Mass/volume] in Blood"),
}
FHIR_FINAL: Final = "final"
FHIR_COMPLETED: Final = "completed"


def neutralize_formula(text: str) -> str:
    """Prefix ``'`` to a cell a spreadsheet would run as a formula (Seguridad 13.4)."""
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


@final
class CsvExportVisitor(ClinicalEventVisitor[tuple[str, str, str, str]]):
    """The type, value, unit and detail cells of an event; no names, no notes."""

    @override
    def visit_glucose_reading(self, event: GlucoseReading) -> tuple[str, str, str, str]:
        context = "" if event.context is None else event.context.value
        return (
            "GLUCOSE",
            str(event.value_mg_dl),
            "mg/dL",
            f"{event.source.value}|{context}",
        )

    @override
    def visit_insulin_dose(self, event: InsulinDose) -> tuple[str, str, str, str]:
        return (
            "INSULIN",
            str(event.units),
            "U",
            f"{event.insulin_kind.value}|{neutralize_formula(event.product_name)}",
        )

    @override
    def visit_meal(self, event: Meal) -> tuple[str, str, str, str]:
        return "MEAL", str(event.carbs_g), "g", event.meal_type.value

    @override
    def visit_physical_activity(
        self, event: PhysicalActivity
    ) -> tuple[str, str, str, str]:
        return (
            "ACTIVITY",
            str(event.duration_min),
            "min",
            f"{neutralize_formula(event.activity_type)}|{event.intensity.value}",
        )

    @override
    def visit_symptom(self, event: Symptom) -> tuple[str, str, str, str]:
        return "SYMPTOM", "", "", neutralize_formula(event.symptom.code)


@final
class CsvTimelineExporter(TimelineExporterPort):
    """The timeline as a CSV file (P21 over ``CsvExportVisitor``)."""

    @override
    def export(self, patient_id: UUID, events: Sequence[ClinicalEvent]) -> ExportedFile:
        visitor = CsvExportVisitor()
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for event in sorted(events, key=lambda item: (item.occurred_at, item.id)):
            event_type, value, unit, detail = event.accept(visitor)
            writer.writerow(
                (
                    event.occurred_at.isoformat(),
                    event_type,
                    event.display_status,
                    event.entry_type.value,
                    value,
                    unit,
                    detail,
                )
            )
        return ExportedFile(
            content=buffer.getvalue().encode(),
            media_type=CSV_MEDIA_TYPE,
            filename="timeline.csv",
        )


type FhirResource = dict[str, object]


def _quantity(value: float, unit: str, code: str) -> dict[str, object]:
    return {"value": value, "unit": unit, "system": UCUM, "code": code}


@final
class FhirExportVisitor(ClinicalEventVisitor[FhirResource]):
    """A FHIR R4 resource per event. The subject is the patient id, never a name.

    The exact content is a proposal (API.md G25): glucose and meals use
    ``Observation`` (LOINC for glucose), the insulin dose uses
    ``MedicationAdministration`` and activities and symptoms use ``Observation``
    with the Insumap code system.
    """

    def __init__(self, patient_id: UUID) -> None:
        self._subject = {"reference": f"Patient/{patient_id}"}

    @override
    def visit_glucose_reading(self, event: GlucoseReading) -> FhirResource:
        code, display = LOINC_BY_SOURCE[event.source]
        return {
            "resourceType": "Observation",
            "id": str(event.id),
            "status": FHIR_FINAL,
            "code": {"coding": [{"system": LOINC, "code": code, "display": display}]},
            "subject": self._subject,
            "effectiveDateTime": event.measured_at.isoformat(),
            "valueQuantity": _quantity(float(event.value_mg_dl), "mg/dL", "mg/dL"),
        }

    @override
    def visit_insulin_dose(self, event: InsulinDose) -> FhirResource:
        return {
            "resourceType": "MedicationAdministration",
            "id": str(event.id),
            "status": FHIR_COMPLETED,
            "medicationCodeableConcept": {"text": event.product_name},
            "subject": self._subject,
            "effectiveDateTime": event.administered_at.isoformat(),
            "dosage": {"dose": _quantity(float(event.units), "U", "[IU]")},
        }

    @override
    def visit_meal(self, event: Meal) -> FhirResource:
        return self._insumap_observation(
            event.id,
            "meal",
            event.eaten_at.isoformat(),
            valueQuantity=_quantity(float(event.carbs_g), "g", "g"),
            note=[{"text": event.meal_type.value}],
        )

    @override
    def visit_physical_activity(self, event: PhysicalActivity) -> FhirResource:
        return self._insumap_observation(
            event.id,
            "physical-activity",
            event.started_at.isoformat(),
            valueQuantity=_quantity(float(event.duration_min), "min", "min"),
            note=[{"text": f"{event.activity_type}|{event.intensity.value}"}],
        )

    @override
    def visit_symptom(self, event: Symptom) -> FhirResource:
        return self._insumap_observation(
            event.id,
            "symptom",
            event.symptom_at.isoformat(),
            valueCodeableConcept={
                "coding": [
                    {"system": INSUMAP_SYMPTOM_SYSTEM, "code": event.symptom.code}
                ]
            },
        )

    def _insumap_observation(
        self, event_id: UUID, code: str, at: str, **value: object
    ) -> FhirResource:
        return {
            "resourceType": "Observation",
            "id": str(event_id),
            "status": FHIR_FINAL,
            "code": {"coding": [{"system": INSUMAP_EVENT_SYSTEM, "code": code}]},
            "subject": self._subject,
            "effectiveDateTime": at,
            **value,
        }


@final
class FhirTimelineExporter(TimelineExporterPort):
    """The timeline as a FHIR R4 ``Bundle`` of type ``collection``."""

    @override
    def export(self, patient_id: UUID, events: Sequence[ClinicalEvent]) -> ExportedFile:
        visitor = FhirExportVisitor(patient_id)
        ordered = sorted(events, key=lambda item: (item.occurred_at, item.id))
        bundle = {
            "resourceType": "Bundle",
            "type": "collection",
            "entry": [{"resource": event.accept(visitor)} for event in ordered],
        }
        return ExportedFile(
            content=json.dumps(bundle, ensure_ascii=False).encode(),
            media_type=FHIR_MEDIA_TYPE,
            filename="timeline.json",
        )
