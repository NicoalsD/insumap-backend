"""PostgreSQL repositories of the patient records (``monitoring`` schema).

Rows are append only: every method here inserts or selects, never updates or
deletes. The lifecycle of a row (corrected or annulled) is derived from the rows
that point at it with ``supersedes_id``. Every statement runs on the session of
the open transaction, under the RLS context the unit of work set.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, cast, final, override
from uuid import UUID

from sqlalchemy import Select, and_, exists, select, tuple_
from sqlalchemy.orm import Session, aliased

from insumap.application.monitoring.paging import PageQuery
from insumap.application.monitoring.ports import (
    ClinicalRecordKind,
    ClinicalRecordPort,
    GlucoseReadingPort,
    ReadingFilters,
    SyncBatchPort,
    TimelinePort,
)
from insumap.domain.monitoring.clinical_event import ClinicalEvent
from insumap.domain.monitoring.glucose import (
    GlucoseReading,
    IssueCode,
    ReadingContext,
    ReadingSource,
    ReadingStatus,
)
from insumap.domain.monitoring.record import (
    ClinicalRecord,
    EntryType,
    RecordLifecycle,
)
from insumap.domain.monitoring.records import (
    ActivityIntensity,
    InsulinDose,
    InsulinKind,
    LabOrigin,
    LabResult,
    LabUnit,
    Meal,
    MealType,
    PhysicalActivity,
    Symptom,
    SymptomEntry,
)
from insumap.domain.monitoring.sync_batch import SyncBatch
from insumap.domain.monitoring.timeline import TimelineEventType
from insumap.domain.monitoring.validation import PreviousReading
from insumap.infrastructure.persistence.monitoring_orm import (
    GlucoseReadingOrm,
    InsulinDoseOrm,
    LabResultOrm,
    MealOrm,
    PhysicalActivityOrm,
    ReadingIssueOrm,
    SymptomCatalogOrm,
    SymptomOrm,
    SyncBatchOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

CORRECTED: Final = "CORRECTED"
VOID: Final = EntryType.VOID.value
type Row = Any


def _lifecycle(superseded_by: str | None) -> RecordLifecycle:
    if superseded_by is None:
        return RecordLifecycle.CURRENT
    if superseded_by == VOID:
        return RecordLifecycle.VOIDED
    return RecordLifecycle.CORRECTED


def _common_columns(record: ClinicalRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "clinic_id": record.clinic_id,
        "patient_id": record.patient_id,
        "recorded_by": record.recorded_by,
        "sync_batch_id": record.sync_batch_id,
        "received_at": record.received_at,
        "entry_type": record.entry_type.value,
        "supersedes_id": record.supersedes_id,
        "correction_reason": record.correction_reason,
    }


def _common_fields(row: Row, superseded_by: str | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "clinic_id": row.clinic_id,
        "patient_id": row.patient_id,
        "recorded_by": row.recorded_by,
        "sync_batch_id": row.sync_batch_id,
        "received_at": row.received_at,
        "entry_type": EntryType(row.entry_type),
        "supersedes_id": row.supersedes_id,
        "correction_reason": row.correction_reason,
        "lifecycle": _lifecycle(superseded_by),
    }


def _superseded_by(orm: type[Any]) -> Any:
    """Scalar subquery: the ``entry_type`` of the row that supersedes this one."""
    other = aliased(orm)
    return (
        select(other.entry_type)
        .where(other.supersedes_id == orm.id)
        .limit(1)
        .correlate(orm)
        .scalar_subquery()
    )


def is_current(orm: type[Any]) -> Any:
    """SQL predicate: not an annulment row and not superseded by any row."""
    other = aliased(orm)
    return and_(
        orm.entry_type != VOID,
        ~exists().where(other.supersedes_id == orm.id).correlate(orm),
    )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class _Kind:
    """What changes from table to table: columns and the two mappers."""

    orm: type[Any]
    time_column: Any
    is_date: bool
    to_orm: Callable[[Any], Any]
    to_domain: Callable[[Row, str | None, dict[UUID, SymptomEntry]], ClinicalRecord]


def _dose_to_orm(record: ClinicalRecord) -> InsulinDoseOrm:
    dose = cast(InsulinDose, record)
    return InsulinDoseOrm(
        **_common_columns(dose),
        client_record_id=dose.client_record_id,
        administered_at=dose.administered_at,
        insulin_kind=dose.insulin_kind.value,
        product_name=dose.product_name,
        units=dose.units,
        plan_id=dose.plan_id,
        note=dose.note,
    )


def _dose_to_domain(
    row: Row, superseded_by: str | None, _: dict[UUID, SymptomEntry]
) -> ClinicalRecord:
    return InsulinDose(
        **_common_fields(row, superseded_by),
        client_record_id=row.client_record_id,
        administered_at=row.administered_at,
        insulin_kind=InsulinKind(row.insulin_kind),
        product_name=row.product_name,
        units=row.units,
        plan_id=row.plan_id,
        note=row.note,
    )


def _meal_to_orm(record: ClinicalRecord) -> MealOrm:
    meal = cast(Meal, record)
    return MealOrm(
        **_common_columns(meal),
        client_record_id=meal.client_record_id,
        eaten_at=meal.eaten_at,
        meal_type=meal.meal_type.value,
        carbs_g=meal.carbs_g,
        note=meal.note,
    )


def _meal_to_domain(
    row: Row, superseded_by: str | None, _: dict[UUID, SymptomEntry]
) -> ClinicalRecord:
    return Meal(
        **_common_fields(row, superseded_by),
        client_record_id=row.client_record_id,
        eaten_at=row.eaten_at,
        meal_type=MealType(row.meal_type),
        carbs_g=row.carbs_g,
        note=row.note,
    )


def _activity_to_orm(record: ClinicalRecord) -> PhysicalActivityOrm:
    activity = cast(PhysicalActivity, record)
    return PhysicalActivityOrm(
        **_common_columns(activity),
        client_record_id=activity.client_record_id,
        started_at=activity.started_at,
        activity_type=activity.activity_type,
        duration_min=activity.duration_min,
        intensity=activity.intensity.value,
        note=activity.note,
    )


def _activity_to_domain(
    row: Row, superseded_by: str | None, _: dict[UUID, SymptomEntry]
) -> ClinicalRecord:
    return PhysicalActivity(
        **_common_fields(row, superseded_by),
        client_record_id=row.client_record_id,
        started_at=row.started_at,
        activity_type=row.activity_type,
        duration_min=row.duration_min,
        intensity=ActivityIntensity(row.intensity),
        note=row.note,
    )


def _symptom_to_orm(record: ClinicalRecord) -> SymptomOrm:
    symptom = cast(Symptom, record)
    return SymptomOrm(
        **_common_columns(symptom),
        client_record_id=symptom.client_record_id,
        occurred_at=symptom.symptom_at,
        symptom_id=symptom.symptom.symptom_id,
        note=symptom.note,
    )


def _symptom_to_domain(
    row: Row, superseded_by: str | None, catalog: dict[UUID, SymptomEntry]
) -> ClinicalRecord:
    return Symptom(
        **_common_fields(row, superseded_by),
        client_record_id=row.client_record_id,
        symptom_at=row.occurred_at,
        symptom=catalog[row.symptom_id],
        note=row.note,
    )


def _lab_to_orm(record: ClinicalRecord) -> LabResultOrm:
    lab = cast(LabResult, record)
    return LabResultOrm(
        **_common_columns(lab),
        client_record_id=lab.client_record_id,
        test_code=lab.test_code,
        performed_on=lab.performed_on,
        value=lab.value,
        unit=lab.unit.value,
        value_pct=lab.value_pct,
        origin=lab.origin.value,
    )


def _lab_to_domain(
    row: Row, superseded_by: str | None, _: dict[UUID, SymptomEntry]
) -> ClinicalRecord:
    return LabResult(
        **_common_fields(row, superseded_by),
        client_record_id=row.client_record_id,
        test_code=row.test_code,
        performed_on=row.performed_on,
        value=row.value,
        unit=LabUnit(row.unit),
        value_pct=row.value_pct,
        origin=LabOrigin(row.origin),
    )


KINDS: Final[dict[ClinicalRecordKind, _Kind]] = {
    ClinicalRecordKind.INSULIN_DOSES: _Kind(
        orm=InsulinDoseOrm,
        time_column=InsulinDoseOrm.administered_at,
        is_date=False,
        to_orm=_dose_to_orm,
        to_domain=_dose_to_domain,
    ),
    ClinicalRecordKind.MEALS: _Kind(
        orm=MealOrm,
        time_column=MealOrm.eaten_at,
        is_date=False,
        to_orm=_meal_to_orm,
        to_domain=_meal_to_domain,
    ),
    ClinicalRecordKind.ACTIVITIES: _Kind(
        orm=PhysicalActivityOrm,
        time_column=PhysicalActivityOrm.started_at,
        is_date=False,
        to_orm=_activity_to_orm,
        to_domain=_activity_to_domain,
    ),
    ClinicalRecordKind.SYMPTOMS: _Kind(
        orm=SymptomOrm,
        time_column=SymptomOrm.occurred_at,
        is_date=False,
        to_orm=_symptom_to_orm,
        to_domain=_symptom_to_domain,
    ),
    ClinicalRecordKind.LAB_RESULTS: _Kind(
        orm=LabResultOrm,
        time_column=LabResultOrm.performed_on,
        is_date=True,
        to_orm=_lab_to_orm,
        to_domain=_lab_to_domain,
    ),
}


KIND_RECORD_TYPES: Final[dict[ClinicalRecordKind, type[ClinicalRecord]]] = {
    ClinicalRecordKind.INSULIN_DOSES: InsulinDose,
    ClinicalRecordKind.MEALS: Meal,
    ClinicalRecordKind.ACTIVITIES: PhysicalActivity,
    ClinicalRecordKind.SYMPTOMS: Symptom,
    ClinicalRecordKind.LAB_RESULTS: LabResult,
}


def _bound(value: datetime, *, is_date: bool) -> datetime | date:
    return value.date() if is_date else value


def _apply_page[S: Select[Any]](
    statement: S, orm: type[Any], time_column: Any, query: PageQuery, *, is_date: bool
) -> S:
    """Date range, keyset cursor and ordering shared by every listing."""
    if query.start is not None:
        statement = statement.where(time_column >= _bound(query.start, is_date=is_date))
    if query.end is not None:
        statement = statement.where(time_column < _bound(query.end, is_date=is_date))
    if query.cursor is not None:
        statement = statement.where(
            tuple_(time_column, orm.id)
            < tuple_(_bound(query.cursor.at, is_date=is_date), query.cursor.id)
        )
    return statement.order_by(time_column.desc(), orm.id.desc()).limit(query.limit)


@final
class ClinicalRecordRepository(ClinicalRecordPort):
    """Insulin doses, meals, activities, symptoms and lab results."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, record: ClinicalRecord) -> None:
        kind = self._kind_of(record)
        session = self._current.get()
        session.add(KINDS[kind].to_orm(record))
        session.flush()

    @override
    def find_by_client_id(
        self, kind: ClinicalRecordKind, patient_id: UUID, client_record_id: UUID
    ) -> ClinicalRecord | None:
        spec = KINDS[kind]
        statement = select(spec.orm, _superseded_by(spec.orm)).where(
            spec.orm.patient_id == patient_id,
            spec.orm.client_record_id == client_record_id,
        )
        return self._first(statement, spec)

    @override
    def get(
        self, kind: ClinicalRecordKind, patient_id: UUID, record_id: UUID
    ) -> ClinicalRecord | None:
        spec = KINDS[kind]
        statement = select(spec.orm, _superseded_by(spec.orm)).where(
            spec.orm.patient_id == patient_id, spec.orm.id == record_id
        )
        return self._first(statement, spec)

    @override
    def list(
        self, kind: ClinicalRecordKind, patient_id: UUID, query: PageQuery
    ) -> Sequence[ClinicalRecord]:
        return self.list_rows(kind, patient_id, query, only_current=False)

    def list_rows(
        self,
        kind: ClinicalRecordKind,
        patient_id: UUID,
        query: PageQuery,
        *,
        only_current: bool,
    ) -> Sequence[ClinicalRecord]:
        """Rows newest first; annulment rows are never listed."""
        spec = KINDS[kind]
        statement = select(spec.orm, _superseded_by(spec.orm)).where(
            spec.orm.patient_id == patient_id, spec.orm.entry_type != VOID
        )
        if only_current:
            statement = statement.where(is_current(spec.orm))
        statement = _apply_page(
            statement, spec.orm, spec.time_column, query, is_date=spec.is_date
        )
        rows = self._current.get().execute(statement).all()
        return self._domain_rows(rows, spec)

    def _first(self, statement: Select[Any], spec: _Kind) -> ClinicalRecord | None:
        rows = self._current.get().execute(statement).all()
        found = self._domain_rows(rows, spec)
        return found[0] if found else None

    def _domain_rows(
        self, rows: Sequence[Any], spec: _Kind
    ) -> Sequence[ClinicalRecord]:
        catalog = (
            _catalog_entries(self._current.get(), {row[0].symptom_id for row in rows})
            if spec.orm is SymptomOrm
            else {}
        )
        return [spec.to_domain(row[0], row[1], catalog) for row in rows]

    @staticmethod
    def _kind_of(record: ClinicalRecord) -> ClinicalRecordKind:
        for kind, record_type in KIND_RECORD_TYPES.items():
            if isinstance(record, record_type):
                return kind
        raise TypeError(type(record).__name__)


def _catalog_entries(session: Session, ids: set[UUID]) -> dict[UUID, SymptomEntry]:
    if not ids:
        return {}
    rows = session.execute(
        select(SymptomCatalogOrm).where(SymptomCatalogOrm.id.in_(ids))
    ).scalars()
    return {
        row.id: SymptomEntry(symptom_id=row.id, code=row.code, is_alarm=row.is_alarm)
        for row in rows
    }


@final
class GlucoseReadingRepository(GlucoseReadingPort):
    """``monitoring.glucose_readings`` with its ``reading_issues``."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, reading: GlucoseReading) -> None:
        session = self._current.get()
        session.add(
            GlucoseReadingOrm(
                **_common_columns(reading),
                client_reading_id=reading.client_record_id,
                measured_at=reading.measured_at,
                value_mg_dl=reading.value_mg_dl,
                source=reading.source.value,
                context=None if reading.context is None else reading.context.value,
                note=reading.note,
                status=reading.status.value,
            )
        )
        session.flush()
        for issue in reading.issues:
            session.add(
                ReadingIssueOrm(
                    clinic_id=reading.clinic_id,
                    reading_id=reading.id,
                    issue_code=issue.value,
                    detail={},
                )
            )
        session.flush()

    @override
    def find_by_client_id(
        self, patient_id: UUID, client_reading_id: UUID
    ) -> GlucoseReading | None:
        return self._first(
            GlucoseReadingOrm.patient_id == patient_id,
            GlucoseReadingOrm.client_reading_id == client_reading_id,
        )

    @override
    def get(self, patient_id: UUID, reading_id: UUID) -> GlucoseReading | None:
        return self._first(
            GlucoseReadingOrm.patient_id == patient_id,
            GlucoseReadingOrm.id == reading_id,
        )

    @override
    def previous_before(
        self, patient_id: UUID, at: datetime, *, excluding: UUID | None = None
    ) -> PreviousReading | None:
        statement = (
            select(GlucoseReadingOrm.value_mg_dl, GlucoseReadingOrm.measured_at)
            .where(
                GlucoseReadingOrm.patient_id == patient_id,
                GlucoseReadingOrm.measured_at < at,
                is_current(GlucoseReadingOrm),
            )
            .order_by(GlucoseReadingOrm.measured_at.desc())
            .limit(1)
        )
        if excluding is not None:
            statement = statement.where(GlucoseReadingOrm.id != excluding)
        row = self._current.get().execute(statement).first()
        if row is None:
            return None
        return PreviousReading(value_mg_dl=row[0], measured_at=row[1])

    @override
    def list(
        self, patient_id: UUID, query: PageQuery, filters: ReadingFilters
    ) -> Sequence[GlucoseReading]:
        orm = GlucoseReadingOrm
        superseded = _superseded_by(orm)
        statement = select(orm, superseded).where(
            orm.patient_id == patient_id, orm.entry_type != VOID
        )
        if filters.source is not None:
            statement = statement.where(orm.source == filters.source.value)
        if filters.status == CORRECTED:
            statement = statement.where(superseded.is_not(None))
        elif filters.status is not None:
            statement = statement.where(
                orm.status == filters.status, superseded.is_(None)
            )
        statement = _apply_page(statement, orm, orm.measured_at, query, is_date=False)
        return self._readings(self._current.get().execute(statement).all())

    def list_rows(
        self, patient_id: UUID, query: PageQuery, *, only_current: bool
    ) -> Sequence[GlucoseReading]:
        """Readings newest first for the timeline and the exports."""
        orm = GlucoseReadingOrm
        statement = select(orm, _superseded_by(orm)).where(
            orm.patient_id == patient_id, orm.entry_type != VOID
        )
        if only_current:
            statement = statement.where(is_current(orm))
        statement = _apply_page(statement, orm, orm.measured_at, query, is_date=False)
        return self._readings(self._current.get().execute(statement).all())

    def _first(self, *conditions: Any) -> GlucoseReading | None:
        orm = GlucoseReadingOrm
        statement = select(orm, _superseded_by(orm)).where(*conditions)
        found = self._readings(self._current.get().execute(statement).all())
        return found[0] if found else None

    def _readings(self, rows: Sequence[Any]) -> Sequence[GlucoseReading]:
        issues = self._issues({row[0].id for row in rows})
        return [
            GlucoseReading(
                **_common_fields(row[0], row[1]),
                client_record_id=row[0].client_reading_id,
                value_mg_dl=row[0].value_mg_dl,
                measured_at=row[0].measured_at,
                source=ReadingSource(row[0].source),
                context=None
                if row[0].context is None
                else ReadingContext(row[0].context),
                note=row[0].note,
                status=ReadingStatus(row[0].status),
                issues=tuple(sorted(issues.get(row[0].id, ()), key=_issue_order)),
            )
            for row in rows
        ]

    def _issues(self, reading_ids: set[UUID]) -> Mapping[UUID, Sequence[IssueCode]]:
        if not reading_ids:
            return {}
        rows = self._current.get().execute(
            select(ReadingIssueOrm.reading_id, ReadingIssueOrm.issue_code).where(
                ReadingIssueOrm.reading_id.in_(reading_ids)
            )
        )
        found: dict[UUID, list[IssueCode]] = {}
        for reading_id, code in rows:
            found.setdefault(reading_id, []).append(IssueCode(code))
        return found


def _issue_order(code: IssueCode) -> int:
    return list(IssueCode).index(code)


@final
class SyncBatchRepository(SyncBatchPort):
    """``monitoring.sync_batches``: written once with the final counts."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, batch: SyncBatch) -> None:
        session = self._current.get()
        session.add(
            SyncBatchOrm(
                id=batch.id,
                clinic_id=batch.clinic_id,
                patient_id=batch.patient_id,
                source=batch.source.value,
                submitted_by=batch.submitted_by,
                total_items=batch.total_items,
                created_count=batch.created_count,
                duplicate_count=batch.duplicate_count,
                rejected_count=batch.rejected_count,
                file_sha256=batch.file_sha256,
                received_at=batch.received_at,
            )
        )
        session.flush()


@final
class TimelineRepository(TimelinePort):
    """The five timeline tables read together and merged by time."""

    TYPE_KINDS: Final = {
        TimelineEventType.INSULIN: ClinicalRecordKind.INSULIN_DOSES,
        TimelineEventType.MEAL: ClinicalRecordKind.MEALS,
        TimelineEventType.ACTIVITY: ClinicalRecordKind.ACTIVITIES,
        TimelineEventType.SYMPTOM: ClinicalRecordKind.SYMPTOMS,
    }

    def __init__(
        self, readings: GlucoseReadingRepository, records: ClinicalRecordRepository
    ) -> None:
        self._readings = readings
        self._records = records

    @override
    def events(
        self,
        patient_id: UUID,
        query: PageQuery,
        types: frozenset[TimelineEventType],
    ) -> Sequence[ClinicalEvent]:
        return self._merged(patient_id, query, types, only_current=False)

    @override
    def effective_events(
        self, patient_id: UUID, query: PageQuery
    ) -> Sequence[ClinicalEvent]:
        return self._merged(
            patient_id, query, frozenset(TimelineEventType), only_current=True
        )

    def _merged(
        self,
        patient_id: UUID,
        query: PageQuery,
        types: frozenset[TimelineEventType],
        *,
        only_current: bool,
    ) -> list[ClinicalEvent]:
        found: list[ClinicalEvent] = []
        if TimelineEventType.GLUCOSE in types:
            found += self._readings.list_rows(
                patient_id, query, only_current=only_current
            )
        for event_type, kind in self.TYPE_KINDS.items():
            if event_type in types:
                for record in self._records.list_rows(
                    kind, patient_id, query, only_current=only_current
                ):
                    found.append(cast(ClinicalEvent, record))
        found.sort(key=lambda event: (event.occurred_at, event.id), reverse=True)
        return found[: query.limit]


__all__ = [
    "ClinicalRecordRepository",
    "GlucoseReadingRepository",
    "SyncBatchRepository",
    "TimelineRepository",
]
