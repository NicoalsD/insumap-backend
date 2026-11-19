"""In-memory doubles of the patient records ports, plus a wired records world."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataResource,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.application.identity.ports import ConsentRepositoryPort, PrivacyNotice
from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.monitoring.glucose import GlucoseReadingRecorder
from insumap.application.monitoring.paging import PageQuery
from insumap.application.monitoring.ports import (
    ActivePlanPort,
    ClinicalRecordKind,
    ClinicalRecordPort,
    GlucoseReadingPort,
    ReadingFilters,
    SymptomCatalogPort,
    SyncBatchPort,
    TimelinePort,
    ValidationSettingsPort,
)
from insumap.domain.identity.consent import ConsentRecord
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from insumap.domain.metrics.target_profile import PatientTargets, TargetProfile
from insumap.domain.metrics.window import GlucosePoint
from insumap.domain.monitoring.clinical_event import ClinicalEvent
from insumap.domain.monitoring.glucose import GlucoseReading
from insumap.domain.monitoring.record import (
    ClinicalRecord,
    EntryType,
    RecordLifecycle,
)
from insumap.domain.monitoring.records import (
    InsulinDose,
    LabResult,
    Meal,
    PhysicalActivity,
    Symptom,
    SymptomEntry,
)
from insumap.domain.monitoring.sync_batch import SyncBatch
from insumap.domain.monitoring.timeline import TimelineEventType
from insumap.domain.monitoring.validation import (
    GlucoseReadingValidationHandler,
    PreviousReading,
    ValidationParams,
    build_validation_chain,
)
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds, FakeUnitOfWorkPort
from tests.support.monitoring_factories import (
    CLINIC_ID,
    NOW,
    PATIENT_ID,
    USER_ID,
    uid,
)

DOCTOR_ID = UUID(int=0xD0)
OTHER_PATIENT_ID = UUID(int=0xA2)

VALIDATION_PARAMS = ValidationParams(
    min_mg_dl=Decimal(20),
    max_mg_dl=Decimal(600),
    future_tolerance=timedelta(minutes=5),
    max_age=timedelta(hours=72),
    duplicate_window=timedelta(minutes=2),
    max_rate_mg_dl_per_min=Decimal(10),
    unit_mismatch_ratio=Decimal(10),
)

# A profile declared by the test, as the database row would be.
TEST_PROFILE = TargetProfile(
    id=uid(900),
    code="TEST_PROFILE",
    version=3,
    population="ADULT",
    range_low_mg_dl=Decimal(70),
    range_high_mg_dl=Decimal(180),
    very_low_mg_dl=Decimal(54),
    very_high_mg_dl=Decimal(250),
    tir_min_pct=Decimal(70),
    tbr_l1_max_pct=Decimal(4),
    tbr_l2_max_pct=Decimal(1),
    tar_l1_max_pct=Decimal(25),
    tar_l2_max_pct=Decimal(5),
    cv_max_pct=Decimal(36),
    min_data_sufficiency_pct=Decimal(70),
    min_days=14,
    max_gap_minutes=20,
    hypo_episode_min_minutes=15,
    min_readings_for_cv=100,
    min_readings_for_cv_smbg=30,
    night_start=datetime(2000, 1, 1, 0, 0).time(),
    night_end=datetime(2000, 1, 1, 6, 0).time(),
)


def patient_actor(*, permissions: frozenset[PermissionCode] | None = None) -> Actor:
    return Actor(
        user_id=USER_ID,
        clinic_id=CLINIC_ID,
        role=Role.PATIENT,
        patient_id=PATIENT_ID,
        permissions=permissions
        if permissions is not None
        else frozenset(
            {
                PermissionCode.GLUCOSE_WRITE_OWN,
                PermissionCode.GLUCOSE_READ_OWN,
                PermissionCode.RECORDS_WRITE_OWN,
                PermissionCode.RECORDS_READ_OWN,
                PermissionCode.RECORDS_CORRECT_OWN,
                PermissionCode.LABS_WRITE_OWN,
                PermissionCode.PATIENTS_READ_OWN,
                PermissionCode.METRICS_READ_OWN,
                PermissionCode.AI_FORECASTS_READ_OWN,
            }
        ),
    )


def doctor_actor(*, permissions: frozenset[PermissionCode] | None = None) -> Actor:
    return Actor(
        user_id=DOCTOR_ID,
        clinic_id=CLINIC_ID,
        role=Role.DOCTOR,
        permissions=permissions
        if permissions is not None
        else frozenset(
            {
                PermissionCode.PATIENTS_READ_ASSIGNED,
                PermissionCode.LABS_WRITE_ASSIGNED,
                PermissionCode.METRICS_READ_ASSIGNED,
                PermissionCode.AI_FORECASTS_READ_ASSIGNED,
            }
        ),
        mfa_verified=True,
    )


class FakeConsentsGate(ConsentRepositoryPort):
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted

    def current_notice(self, clinic_id: UUID) -> PrivacyNotice | None:
        return None

    def add(self, records: Sequence[ConsentRecord]) -> None:
        raise NotImplementedError

    def has_accepted_current(self, patient_id: UUID, clinic_id: UUID) -> bool:
        return self.accepted


class FakePatientRecords(PatientRecordPort):
    """The access chain: only the listed doctor/patient pairs are assigned."""

    def __init__(self) -> None:
        self.assigned: set[tuple[UUID, UUID]] = {(DOCTOR_ID, PATIENT_ID)}
        self.reads: list[tuple[UUID, UUID, AccessPurpose]] = []

    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
    ) -> PatientRecord:
        del resource
        self.reads.append((actor.user_id, patient_id, purpose))
        if (actor.user_id, patient_id) not in self.assigned:
            raise InsumapError(ErrorCode.NOT_FOUND)
        return PatientRecord(patient_id=patient_id, clinic_id=CLINIC_ID)


def _lifecycle_of(
    rows: Sequence[ClinicalRecord], record: ClinicalRecord
) -> RecordLifecycle:
    for other in rows:
        if other.supersedes_id == record.id:
            return (
                RecordLifecycle.VOIDED
                if other.entry_type is EntryType.VOID
                else RecordLifecycle.CORRECTED
            )
    return RecordLifecycle.CURRENT


def _page[T: ClinicalRecord](rows: Sequence[T], query: PageQuery) -> list[T]:
    ordered = sorted(rows, key=lambda r: (r.occurred_at, r.id), reverse=True)
    if query.start is not None:
        ordered = [r for r in ordered if r.occurred_at >= query.start]
    if query.end is not None:
        ordered = [r for r in ordered if r.occurred_at < query.end]
    if query.cursor is not None:
        key = (query.cursor.at, query.cursor.id)
        ordered = [r for r in ordered if (r.occurred_at, r.id) < key]
    return ordered[: query.limit]


class FakeGlucoseReadings(GlucoseReadingPort):
    def __init__(self) -> None:
        self.rows: list[GlucoseReading] = []

    def add(self, reading: GlucoseReading) -> None:
        self.rows.append(reading)

    def _hydrated(self, row: GlucoseReading) -> GlucoseReading:
        return replace(row, lifecycle=_lifecycle_of(self.rows, row))

    def find_by_client_id(
        self, patient_id: UUID, client_reading_id: UUID
    ) -> GlucoseReading | None:
        for row in self.rows:
            if (
                row.patient_id == patient_id
                and row.client_record_id == client_reading_id
            ):
                return self._hydrated(row)
        return None

    def get(self, patient_id: UUID, reading_id: UUID) -> GlucoseReading | None:
        for row in self.rows:
            if row.patient_id == patient_id and row.id == reading_id:
                return self._hydrated(row)
        return None

    def previous_before(
        self, patient_id: UUID, at: datetime, *, excluding: UUID | None = None
    ) -> PreviousReading | None:
        earlier = [
            row
            for row in self.rows
            if row.patient_id == patient_id
            and row.measured_at < at
            and row.id != excluding
            and row.entry_type is not EntryType.VOID
        ]
        if not earlier:
            return None
        last = max(earlier, key=lambda row: row.measured_at)
        return PreviousReading(
            value_mg_dl=last.value_mg_dl, measured_at=last.measured_at
        )

    def list(
        self, patient_id: UUID, query: PageQuery, filters: ReadingFilters
    ) -> Sequence[GlucoseReading]:
        mine = [self._hydrated(r) for r in self.rows if r.patient_id == patient_id]
        if filters.source is not None:
            mine = [r for r in mine if r.source is filters.source]
        if filters.status is not None:
            mine = [r for r in mine if r.display_status == filters.status]
        return _page(mine, query)


class FakeClinicalRecords(ClinicalRecordPort):
    def __init__(self) -> None:
        self.rows: dict[ClinicalRecordKind, list[ClinicalRecord]] = {
            kind: [] for kind in ClinicalRecordKind
        }

    def _kind_of(self, record: ClinicalRecord) -> ClinicalRecordKind:
        mapping: dict[type, ClinicalRecordKind] = {
            InsulinDose: ClinicalRecordKind.INSULIN_DOSES,
            Meal: ClinicalRecordKind.MEALS,
            PhysicalActivity: ClinicalRecordKind.ACTIVITIES,
            Symptom: ClinicalRecordKind.SYMPTOMS,
            LabResult: ClinicalRecordKind.LAB_RESULTS,
        }
        return mapping[type(record)]

    def add(self, record: ClinicalRecord) -> None:
        self.rows[self._kind_of(record)].append(record)

    def _hydrated(
        self, kind: ClinicalRecordKind, record: ClinicalRecord
    ) -> ClinicalRecord:
        return replace(record, lifecycle=_lifecycle_of(self.rows[kind], record))

    def find_by_client_id(
        self, kind: ClinicalRecordKind, patient_id: UUID, client_record_id: UUID
    ) -> ClinicalRecord | None:
        for row in self.rows[kind]:
            if (
                row.patient_id == patient_id
                and row.client_record_id == client_record_id
            ):
                return self._hydrated(kind, row)
        return None

    def get(
        self, kind: ClinicalRecordKind, patient_id: UUID, record_id: UUID
    ) -> ClinicalRecord | None:
        for row in self.rows[kind]:
            if row.patient_id == patient_id and row.id == record_id:
                return self._hydrated(kind, row)
        return None

    def list(
        self, kind: ClinicalRecordKind, patient_id: UUID, query: PageQuery
    ) -> Sequence[ClinicalRecord]:
        mine = [
            self._hydrated(kind, r)
            for r in self.rows[kind]
            if r.patient_id == patient_id
        ]
        return _page(mine, query)


class FakeTimeline(TimelinePort):
    def __init__(self, readings: FakeGlucoseReadings, records: FakeClinicalRecords):
        self._readings = readings
        self._records = records

    def _all(self, patient_id: UUID) -> list[ClinicalEvent]:
        found: list[ClinicalEvent] = []
        found += [r for r in self._readings.rows if r.patient_id == patient_id]
        for kind in (
            ClinicalRecordKind.INSULIN_DOSES,
            ClinicalRecordKind.MEALS,
            ClinicalRecordKind.ACTIVITIES,
            ClinicalRecordKind.SYMPTOMS,
        ):
            for row in self._records.rows[kind]:
                if row.patient_id == patient_id:
                    assert isinstance(
                        row, InsulinDose | Meal | PhysicalActivity | Symptom
                    )
                    found.append(row)
        return found

    def events(
        self,
        patient_id: UUID,
        query: PageQuery,
        types: frozenset[TimelineEventType],
    ) -> Sequence[ClinicalEvent]:
        wanted = {
            TimelineEventType.GLUCOSE: GlucoseReading,
            TimelineEventType.INSULIN: InsulinDose,
            TimelineEventType.MEAL: Meal,
            TimelineEventType.ACTIVITY: PhysicalActivity,
            TimelineEventType.SYMPTOM: Symptom,
        }
        rows = [
            e
            for e in self._all(patient_id)
            if isinstance(e, tuple(wanted[t] for t in types))
            and e.entry_type is not EntryType.VOID
        ]
        return _page(rows, query)

    def effective_events(
        self, patient_id: UUID, query: PageQuery
    ) -> Sequence[ClinicalEvent]:
        everything = self._all(patient_id)
        current = [
            e
            for e in everything
            if e.entry_type is not EntryType.VOID
            and _lifecycle_of(everything, e) is RecordLifecycle.CURRENT
        ]
        return _page(current, query)


class FakeSettings(ValidationSettingsPort):
    def __init__(self) -> None:
        self.params = VALIDATION_PARAMS

    def active_for(self, clinic_id: UUID) -> ValidationParams:
        return self.params


class FakeTargets(TargetProfilePort):
    def __init__(self) -> None:
        self.targets: PatientTargets | None = PatientTargets(
            patient_id=PATIENT_ID, profile=TEST_PROFILE, timezone="America/Bogota"
        )

    def for_patient(self, patient_id: UUID) -> PatientTargets | None:
        return self.targets


class FakeSeries(GlucoseSeriesPort):
    def __init__(self) -> None:
        self.points_by_patient: dict[UUID, list[GlucosePoint]] = {}

    def points(
        self, patient_id: UUID, start: datetime, end: datetime
    ) -> Sequence[GlucosePoint]:
        return [
            p for p in self.points_by_patient.get(patient_id, []) if start <= p.at < end
        ]


class FakeSyncBatches(SyncBatchPort):
    def __init__(self) -> None:
        self.batches: list[SyncBatch] = []

    def add(self, batch: SyncBatch) -> None:
        self.batches.append(batch)


class FakeCatalog(SymptomCatalogPort):
    def __init__(self) -> None:
        self.entries = {
            "THIRST": SymptomEntry(symptom_id=uid(500), code="THIRST", is_alarm=False),
            "CONFUSION": SymptomEntry(
                symptom_id=uid(501), code="CONFUSION", is_alarm=True
            ),
        }

    def find_active(self, clinic_id: UUID, code: str) -> SymptomEntry | None:
        return self.entries.get(code)


class FakePlans(ActivePlanPort):
    def __init__(self) -> None:
        self.plan_id: UUID | None = uid(700)

    def active_plan_id(self, patient_id: UUID) -> UUID | None:
        return self.plan_id


@dataclass
class RecordsWorld:
    """The ports of the records module over in-memory doubles."""

    clock: FixedClock = field(default_factory=lambda: FixedClock(NOW))
    uow: FakeUnitOfWorkPort = field(default_factory=FakeUnitOfWorkPort)
    ids: FakeIds = field(default_factory=FakeIds)
    consents: FakeConsentsGate = field(default_factory=FakeConsentsGate)
    patients: FakePatientRecords = field(default_factory=FakePatientRecords)
    readings: FakeGlucoseReadings = field(default_factory=FakeGlucoseReadings)
    records: FakeClinicalRecords = field(default_factory=FakeClinicalRecords)
    settings: FakeSettings = field(default_factory=FakeSettings)
    targets: FakeTargets = field(default_factory=FakeTargets)
    batches: FakeSyncBatches = field(default_factory=FakeSyncBatches)
    catalog: FakeCatalog = field(default_factory=FakeCatalog)
    plans: FakePlans = field(default_factory=FakePlans)
    series: FakeSeries = field(default_factory=FakeSeries)

    @property
    def own_gate(self) -> OwnPatientGate:
        return OwnPatientGate(self.consents)

    @property
    def assigned_gate(self) -> AssignedPatientGate:
        return AssignedPatientGate(self.patients)

    @property
    def timeline(self) -> FakeTimeline:
        return FakeTimeline(self.readings, self.records)

    @property
    def chain(self) -> GlucoseReadingValidationHandler:
        return build_validation_chain()

    @property
    def recorder(self) -> GlucoseReadingRecorder:
        return GlucoseReadingRecorder(
            readings=self.readings,
            chain=build_validation_chain(),
            settings=self.settings,
            targets=self.targets,
            ids=self.ids,
            clock=self.clock,
        )
