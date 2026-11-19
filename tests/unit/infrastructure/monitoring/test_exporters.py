"""CSV and FHIR exports of the timeline: formula neutralization and the bundle."""

import csv
import io
import json
from uuid import UUID

from insumap.domain.monitoring.clinical_event import ClinicalEvent
from insumap.domain.monitoring.glucose import ReadingSource
from insumap.infrastructure.monitoring.exporters import (
    CsvTimelineExporter,
    FhirTimelineExporter,
    neutralize_formula,
)
from tests.support.monitoring_factories import (
    PATIENT_ID,
    make_activity,
    make_dose,
    make_meal,
    make_reading,
    make_symptom,
)

EVENTS: list[ClinicalEvent] = [
    make_reading(1),
    make_dose(2),
    make_meal(3),
    make_activity(4),
    make_symptom(5),
]


def test_csv_has_a_header_and_one_row_per_event_without_identifiers() -> None:
    exported = CsvTimelineExporter().export(PATIENT_ID, EVENTS)

    rows = list(csv.reader(io.StringIO(exported.content.decode())))
    assert rows[0][:3] == ["occurred_at", "event_type", "status"]
    assert len(rows) == 1 + len(EVENTS)
    assert {row[1] for row in rows[1:]} == {
        "GLUCOSE",
        "INSULIN",
        "MEAL",
        "ACTIVITY",
        "SYMPTOM",
    }
    assert str(PATIENT_ID) not in exported.content.decode()
    assert exported.media_type.startswith("text/csv")


def test_csv_neutralizes_cells_a_spreadsheet_would_run_as_formulas() -> None:
    events: list[ClinicalEvent] = [
        make_dose(2, name='=HYPERLINK("http://x")'),
        make_activity(4, kind="+cmd"),
    ]

    text = CsvTimelineExporter().export(PATIENT_ID, events).content.decode()

    assert "'=HYPERLINK" in text
    assert "'+cmd" in text


def test_neutralize_formula_covers_every_dangerous_prefix() -> None:
    for prefix in ("=", "+", "-", "@", "\t", "\r"):
        assert neutralize_formula(f"{prefix}x") == f"'{prefix}x"
    assert neutralize_formula("Glargina") == "Glargina"


def test_fhir_bundle_has_a_resource_per_event_with_loinc_for_glucose() -> None:
    exported = FhirTimelineExporter().export(PATIENT_ID, EVENTS)

    bundle = json.loads(exported.content)
    types = [entry["resource"]["resourceType"] for entry in bundle["entry"]]
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert types.count("Observation") == 4
    assert types.count("MedicationAdministration") == 1
    glucose = next(
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["valueQuantity"]["code"] == "mg/dL"
    )
    assert glucose["code"]["coding"][0]["code"] == "41653-7"
    assert glucose["subject"] == {"reference": f"Patient/{PATIENT_ID}"}
    assert exported.media_type == "application/fhir+json"


def test_fhir_uses_the_loinc_of_each_glucose_source() -> None:
    cgm = make_reading(1, source=ReadingSource.CGM)
    manual = make_reading(2, source=ReadingSource.MANUAL)

    bundle = json.loads(
        FhirTimelineExporter().export(UUID(int=1), [cgm, manual]).content
    )

    codes = {e["resource"]["code"]["coding"][0]["code"] for e in bundle["entry"]}
    assert codes == {"99504-3", "2339-0"}
