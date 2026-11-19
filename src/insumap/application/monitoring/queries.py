"""Listings, timeline and export of the patient records (own and assigned)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWorkPort,
)
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.monitoring.paging import Cursor, Page, PageQuery
from insumap.application.monitoring.ports import (
    ClinicalRecordKind,
    ClinicalRecordPort,
    GlucoseReadingPort,
    ReadingFilters,
    TimelinePort,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.clinical_event import ClinicalEvent
from insumap.domain.monitoring.record import ClinicalRecord
from insumap.domain.monitoring.timeline import (
    TimelineEventType,
    TimelineItem,
    build_timeline,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

RANGE_FIELD: Final = "query.to"


class ListableKind(StrEnum):
    """What a listing endpoint returns."""

    READINGS = "readings"
    INSULIN_DOSES = "insulin-doses"
    MEALS = "meals"
    ACTIVITIES = "activities"
    SYMPTOMS = "symptoms"
    LAB_RESULTS = "lab-results"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ListRequest:
    """``from``, ``to``, ``limit`` and ``cursor`` of a listing."""

    start: datetime | None = None
    end: datetime | None = None
    limit: int = FieldLimits.PAGE_SIZE_DEFAULT
    cursor: str | None = None

    def to_query(self) -> PageQuery:
        """The repository query (one extra row tells whether there is a next page)."""
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise InsumapError(
                ErrorCode.VALIDATION_ERROR,
                detail={"errors": [{"field": RANGE_FIELD, "type": "invalid_range"}]},
            )
        return PageQuery(
            limit=self.limit + 1,
            cursor=None if self.cursor is None else Cursor.decode(self.cursor),
            start=self.start,
            end=self.end,
        )


def paginate[T](
    rows: Sequence[T], limit: int, at_and_id: Callable[[T], tuple[datetime, UUID]]
) -> tuple[tuple[T, ...], str | None]:
    """Cut the extra row off and build the cursor of the next page."""
    if len(rows) <= limit:
        return tuple(rows), None
    items = tuple(rows[:limit])
    at, row_id = at_and_id(items[-1])
    return items, Cursor(at=at, id=row_id).encode()


def _record_key(record: ClinicalRecord) -> tuple[datetime, UUID]:
    return record.occurred_at, record.id


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ListRecordsInput:
    """A listing of the own records (``patient_id`` ``None``) or of an assigned one."""

    actor: Actor
    kind: ListableKind
    request: ListRequest
    patient_id: UUID | None = None
    filters: ReadingFilters = field(default_factory=ReadingFilters)


@final
class ListRecordsUseCase:
    """``GET /readings``, ``/insulin-doses``, ``/meals``... and the doctor's reads."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        readings: GlucoseReadingPort,
        records: ClinicalRecordPort,
    ) -> None:
        self._uow = uow
        self._own_gate = own_gate
        self._assigned_gate = assigned_gate
        self._readings = readings
        self._records = records

    def execute(self, input: ListRecordsInput) -> Page[ClinicalRecord]:
        """One page of records, newest first, with their lifecycle."""
        query = input.request.to_query()
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)):
            if input.patient_id is None:
                permission = (
                    PermissionCode.GLUCOSE_READ_OWN
                    if input.kind is ListableKind.READINGS
                    else PermissionCode.RECORDS_READ_OWN
                )
                patient_id = self._own_gate.enter(actor, permission).patient_id
            else:
                patient_id = self._assigned_gate.enter(
                    actor, PermissionCode.PATIENTS_READ_ASSIGNED, input.patient_id
                )
            rows: Sequence[ClinicalRecord]
            if input.kind is ListableKind.READINGS:
                rows = self._readings.list(patient_id, query, input.filters)
            else:
                rows = self._records.list(
                    ClinicalRecordKind(input.kind.value), patient_id, query
                )
        items, next_cursor = paginate(rows, input.request.limit, _record_key)
        return Page(items=items, next_cursor=next_cursor)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class TimelineInput:
    actor: Actor
    request: ListRequest
    patient_id: UUID | None = None
    event_types: frozenset[TimelineEventType] = frozenset(TimelineEventType)


@final
class GetTimelineUseCase:
    """``GET /timeline`` and ``GET /patients/{patient_id}/timeline`` (P21)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        timeline: TimelinePort,
    ) -> None:
        self._uow = uow
        self._own_gate = own_gate
        self._assigned_gate = assigned_gate
        self._timeline = timeline

    def execute(self, input: TimelineInput) -> Page[TimelineItem]:
        """Events of the five kinds ordered by time, newest first."""
        query = input.request.to_query()
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)):
            if input.patient_id is None:
                patient_id = self._own_gate.enter(
                    actor, PermissionCode.RECORDS_READ_OWN
                ).patient_id
            else:
                patient_id = self._assigned_gate.enter(
                    actor, PermissionCode.PATIENTS_READ_ASSIGNED, input.patient_id
                )
            events = self._timeline.events(patient_id, query, input.event_types)
        page, next_cursor = paginate(events, input.request.limit, _event_key)
        return Page(items=build_timeline(page), next_cursor=next_cursor)


def _event_key(event: ClinicalEvent) -> tuple[datetime, UUID]:
    return event.occurred_at, event.id


class ExportFormat(StrEnum):
    CSV = "csv"
    FHIR = "fhir"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ExportedFile:
    """The bytes of an export with the content type and a neutral file name."""

    content: bytes
    media_type: str
    filename: str


class TimelineExporterPort(ABC):
    """Writes the events of a patient in one format (visitors, P21)."""

    @abstractmethod
    def export(self, patient_id: UUID, events: Sequence[ClinicalEvent]) -> ExportedFile:
        """Render ``events`` as a file."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ExportTimelineInput:
    actor: Actor
    format: ExportFormat
    start: datetime | None = None
    end: datetime | None = None
    patient_id: UUID | None = None


@final
class ExportTimelineUseCase:
    """``GET /timeline/export`` and ``GET /patients/{patient_id}/timeline/export``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        timeline: TimelinePort,
        exporters: dict[ExportFormat, TimelineExporterPort],
    ) -> None:
        self._uow = uow
        self._own_gate = own_gate
        self._assigned_gate = assigned_gate
        self._timeline = timeline
        self._exporters = exporters

    def execute(self, input: ExportTimelineInput) -> ExportedFile:
        """The current events of the range as CSV or FHIR."""
        request = ListRequest(
            start=input.start, end=input.end, limit=FieldLimits.EXPORT_MAX_EVENTS
        )
        query = request.to_query()
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)):
            if input.patient_id is None:
                patient_id = self._own_gate.enter(
                    actor, PermissionCode.RECORDS_READ_OWN
                ).patient_id
            else:
                patient_id = self._assigned_gate.enter(
                    actor, PermissionCode.PATIENTS_READ_ASSIGNED, input.patient_id
                )
            events = self._timeline.effective_events(patient_id, query)
        if len(events) > FieldLimits.EXPORT_MAX_EVENTS:
            raise InsumapError(
                ErrorCode.VALIDATION_ERROR,
                detail={"errors": [{"field": RANGE_FIELD, "type": "range_too_large"}]},
            )
        return self._exporters[input.format].export(patient_id, events)
