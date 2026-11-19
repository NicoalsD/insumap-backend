"""Listings, timeline and export: own and assigned, pagination and access."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest

from insumap.application.monitoring.paging import Cursor
from insumap.application.monitoring.ports import ReadingFilters
from insumap.application.monitoring.queries import (
    ExportFormat,
    ExportTimelineInput,
    ExportTimelineUseCase,
    GetTimelineUseCase,
    ListableKind,
    ListRecordsInput,
    ListRecordsUseCase,
    ListRequest,
    TimelineInput,
)
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.monitoring.record import RecordLifecycle
from insumap.domain.monitoring.timeline import TimelineEventType
from insumap.infrastructure.monitoring.exporters import (
    CsvTimelineExporter,
    FhirTimelineExporter,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits
from tests.support.monitoring_factories import (
    NOW,
    PATIENT_ID,
    make_dose,
    make_meal,
    make_reading,
)
from tests.support.monitoring_fakes import (
    OTHER_PATIENT_ID,
    RecordsWorld,
    doctor_actor,
    patient_actor,
)


@pytest.fixture
def world() -> RecordsWorld:
    world = RecordsWorld()
    for number in range(1, 6):
        world.readings.add(make_reading(number, at=NOW - timedelta(minutes=number)))
    return world


def lister(world: RecordsWorld) -> ListRecordsUseCase:
    return ListRecordsUseCase(
        uow=world.uow,
        own_gate=world.own_gate,
        assigned_gate=world.assigned_gate,
        readings=world.readings,
        records=world.records,
    )


def test_own_readings_are_paginated_newest_first_with_a_cursor(
    world: RecordsWorld,
) -> None:
    first = lister(world).execute(
        ListRecordsInput(
            actor=patient_actor(),
            kind=ListableKind.READINGS,
            request=ListRequest(limit=2),
        )
    )
    assert [r.id for r in first.items] == [UUID(int=1), UUID(int=2)]
    assert first.next_cursor is not None

    second = lister(world).execute(
        ListRecordsInput(
            actor=patient_actor(),
            kind=ListableKind.READINGS,
            request=ListRequest(limit=2, cursor=first.next_cursor),
        )
    )
    assert [r.id for r in second.items] == [UUID(int=3), UUID(int=4)]
    last = lister(world).execute(
        ListRecordsInput(
            actor=patient_actor(),
            kind=ListableKind.READINGS,
            request=ListRequest(limit=2, cursor=second.next_cursor),
        )
    )
    assert [r.id for r in last.items] == [UUID(int=5)]
    assert last.next_cursor is None


def test_a_cursor_nobody_issued_is_a_validation_error(world: RecordsWorld) -> None:
    for bad in ("not-a-cursor", "e30", ""):
        with pytest.raises(InsumapError) as caught:
            lister(world).execute(
                ListRecordsInput(
                    actor=patient_actor(),
                    kind=ListableKind.READINGS,
                    request=ListRequest(cursor=bad),
                )
            )
        assert caught.value.code is ErrorCode.VALIDATION_ERROR


def test_a_cursor_round_trips() -> None:
    cursor = Cursor(at=NOW, id=UUID(int=7))

    assert Cursor.decode(cursor.encode()) == cursor


def test_the_date_range_filters_and_must_be_ordered(world: RecordsWorld) -> None:
    page = lister(world).execute(
        ListRecordsInput(
            actor=patient_actor(),
            kind=ListableKind.READINGS,
            request=ListRequest(start=NOW - timedelta(minutes=3), end=NOW),
        )
    )
    assert len(page.items) == 3
    with pytest.raises(InsumapError):
        ListRequest(start=NOW, end=NOW - timedelta(days=1)).to_query()


def test_readings_filter_by_status_including_corrected(world: RecordsWorld) -> None:
    world.readings.rows[0] = replace(
        world.readings.rows[0], lifecycle=RecordLifecycle.CORRECTED
    )
    superseding = replace(
        make_reading(9), supersedes_id=UUID(int=1), correction_reason="x" * 10
    )
    world.readings.add(superseding)

    page = lister(world).execute(
        ListRecordsInput(
            actor=patient_actor(),
            kind=ListableKind.READINGS,
            request=ListRequest(),
            filters=ReadingFilters(status="CORRECTED"),
        )
    )

    assert [r.id for r in page.items] == [UUID(int=1)]


def test_a_doctor_reads_an_assigned_patient_through_the_access_port(
    world: RecordsWorld,
) -> None:
    page = lister(world).execute(
        ListRecordsInput(
            actor=doctor_actor(),
            kind=ListableKind.READINGS,
            request=ListRequest(),
            patient_id=PATIENT_ID,
        )
    )

    assert len(page.items) == 5
    assert world.patients.reads[0][:2] == (doctor_actor().user_id, PATIENT_ID)
    assert world.uow.commits == 1  # the audit row of the read is kept


def test_a_patient_that_is_not_assigned_answers_not_found(world: RecordsWorld) -> None:
    with pytest.raises(InsumapError) as caught:
        lister(world).execute(
            ListRecordsInput(
                actor=doctor_actor(),
                kind=ListableKind.READINGS,
                request=ListRequest(),
                patient_id=OTHER_PATIENT_ID,
            )
        )

    assert caught.value.code is ErrorCode.NOT_FOUND


def test_reading_requires_the_matching_permission(world: RecordsWorld) -> None:
    only_records = patient_actor(
        permissions=patient_actor().permissions
        - {p for p in patient_actor().permissions if p.value == "glucose.read_own"}
    )
    with pytest.raises(PermissionDeniedError):
        lister(world).execute(
            ListRecordsInput(
                actor=only_records,
                kind=ListableKind.READINGS,
                request=ListRequest(),
            )
        )
    # records.read_own still lists the other kinds.
    page = lister(world).execute(
        ListRecordsInput(
            actor=only_records, kind=ListableKind.MEALS, request=ListRequest()
        )
    )
    assert page.items == ()


def timeline(world: RecordsWorld) -> GetTimelineUseCase:
    return GetTimelineUseCase(
        uow=world.uow,
        own_gate=world.own_gate,
        assigned_gate=world.assigned_gate,
        timeline=world.timeline,
    )


def test_the_timeline_mixes_the_five_kinds_and_filters_by_type(
    world: RecordsWorld,
) -> None:
    world.records.add(make_dose(20))
    world.records.add(make_meal(21))

    everything = timeline(world).execute(
        TimelineInput(actor=patient_actor(), request=ListRequest(limit=50))
    )
    only_meals = timeline(world).execute(
        TimelineInput(
            actor=patient_actor(),
            request=ListRequest(),
            event_types=frozenset({TimelineEventType.MEAL}),
        )
    )

    assert len(everything.items) == 7
    kinds = [item.event_type for item in only_meals.items]
    assert kinds == [TimelineEventType.MEAL]


def test_the_timeline_cursor_pages_over_merged_tables(world: RecordsWorld) -> None:
    world.records.add(make_meal(21))
    seen: list[UUID] = []
    cursor: str | None = None
    for _ in range(10):
        page = timeline(world).execute(
            TimelineInput(
                actor=patient_actor(), request=ListRequest(limit=2, cursor=cursor)
            )
        )
        seen += [item.id for item in page.items]
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 6


def test_a_doctor_reads_the_timeline_of_an_assigned_patient(
    world: RecordsWorld,
) -> None:
    page = timeline(world).execute(
        TimelineInput(
            actor=doctor_actor(), request=ListRequest(), patient_id=PATIENT_ID
        )
    )

    assert page.items
    with pytest.raises(InsumapError):
        timeline(world).execute(
            TimelineInput(
                actor=doctor_actor(),
                request=ListRequest(),
                patient_id=OTHER_PATIENT_ID,
            )
        )


def exporter(world: RecordsWorld) -> ExportTimelineUseCase:
    return ExportTimelineUseCase(
        uow=world.uow,
        own_gate=world.own_gate,
        assigned_gate=world.assigned_gate,
        timeline=world.timeline,
        exporters={
            ExportFormat.CSV: CsvTimelineExporter(),
            ExportFormat.FHIR: FhirTimelineExporter(),
        },
    )


def test_the_export_has_only_current_events(world: RecordsWorld) -> None:
    world.readings.add(
        replace(make_reading(9), supersedes_id=UUID(int=1), correction_reason="x" * 10)
    )

    csv_file = exporter(world).execute(
        ExportTimelineInput(actor=patient_actor(), format=ExportFormat.CSV)
    )
    fhir_file = exporter(world).execute(
        ExportTimelineInput(actor=patient_actor(), format=ExportFormat.FHIR)
    )

    assert csv_file.media_type.startswith("text/csv")
    assert csv_file.content.decode().count("GLUCOSE") == 5
    assert fhir_file.media_type == "application/fhir+json"


def test_a_doctor_exports_an_assigned_patient_and_is_denied_a_stranger(
    world: RecordsWorld,
) -> None:
    exported = exporter(world).execute(
        ExportTimelineInput(
            actor=doctor_actor(), format=ExportFormat.CSV, patient_id=PATIENT_ID
        )
    )
    assert exported.filename == "timeline.csv"
    with pytest.raises(InsumapError):
        exporter(world).execute(
            ExportTimelineInput(
                actor=doctor_actor(),
                format=ExportFormat.CSV,
                patient_id=OTHER_PATIENT_ID,
            )
        )


def test_an_export_over_the_event_limit_is_refused(
    world: RecordsWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FieldLimits, "EXPORT_MAX_EVENTS", 2)

    with pytest.raises(InsumapError) as caught:
        exporter(world).execute(
            ExportTimelineInput(actor=patient_actor(), format=ExportFormat.CSV)
        )

    assert caught.value.code is ErrorCode.VALIDATION_ERROR
