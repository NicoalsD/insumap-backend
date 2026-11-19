"""Record insulin doses, meals, activities, symptoms and lab results (append only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast, final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWork,
    UnitOfWorkPort,
)
from insumap.application.monitoring.data import (
    ActivityData,
    InsulinData,
    LabData,
    MealData,
    SymptomData,
)
from insumap.application.monitoring.gate import (
    AssignedPatientGate,
    OwnPatientGate,
)
from insumap.application.monitoring.ports import (
    ActivePlanPort,
    ClinicalRecordKind,
    ClinicalRecordPort,
    SymptomCatalogPort,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.record import ClinicalRecord
from insumap.domain.monitoring.records import (
    InsulinDose,
    LabOrigin,
    LabResult,
    Meal,
    PhysicalActivity,
    Symptom,
    SymptomEntry,
    hba1c_to_percent,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

HBA1C_TEST_CODE = "HBA1C"
LIPOHYPERTROPHY_CODE = "LIPOHYPERTROPHY"
INJECTION_SITE_FIELD = "body.injection_site"
SYMPTOM_FIELD = "body.symptom_code"


def require_site_for(entry: SymptomEntry, data: SymptomData) -> None:
    """Lipohypertrophy is about a place: without a site it is a ``422``."""
    if entry.code == LIPOHYPERTROPHY_CODE and data.injection_site is None:
        raise InsumapError(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [{"field": INJECTION_SITE_FIELD, "type": "site_required"}]
            },
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecordInput[D]:
    """The actor, the optional id the client generated and the typed values."""

    actor: Actor
    data: D
    client_record_id: UUID | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AssignedLabInput:
    """A doctor registers an HbA1c result of an assigned patient."""

    actor: Actor
    patient_id: UUID
    data: LabData
    client_record_id: UUID | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RecordedRecord[R: ClinicalRecord]:
    """The saved record; ``created`` is ``False`` when it was already there."""

    record: R
    created: bool


@final
class RecordWriter:
    """Idempotent insert of one record by its client id (same content: no-op)."""

    def __init__(self, records: ClinicalRecordPort) -> None:
        self._records = records

    def write[R: ClinicalRecord](
        self, uow: UnitOfWork, kind: ClinicalRecordKind, record: R
    ) -> RecordedRecord[R]:
        """Insert ``record`` or return the one the client already sent."""
        existing = self._records.find_by_client_id(
            kind, record.patient_id, record.client_record_id
        )
        if existing is not None:
            if not record.has_same_content(existing):
                raise InsumapError(ErrorCode.CONFLICT)
            return RecordedRecord(record=cast("R", existing), created=False)
        self._records.add(record)
        uow.collect(record.pending_events)
        return RecordedRecord(record=record, created=True)


@final
class RecordInsulinDoseUseCase:
    """``POST /insulin-doses``: only what the patient says; never a suggestion."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        writer: RecordWriter,
        plans: ActivePlanPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._writer = writer
        self._plans = plans
        self._ids = ids
        self._clock = clock

    def execute(self, input: RecordInput[InsulinData]) -> RecordedRecord[InsulinDose]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.RECORDS_WRITE_OWN)
            data = input.data
            dose = InsulinDose(
                id=self._ids.new_id(),
                clinic_id=scope.clinic_id,
                patient_id=scope.patient_id,
                client_record_id=input.client_record_id or self._ids.new_id(),
                recorded_by=input.actor.user_id,
                received_at=self._clock.now(),
                administered_at=data.administered_at,
                insulin_kind=data.insulin_kind,
                product_name=data.product_name,
                units=data.units,
                plan_id=self._plans.active_plan_id(scope.patient_id),
                note=data.note,
                injection_site=data.injection_site,
                injection_spot=data.injection_spot,
            )
            recorded = self._writer.write(uow, ClinicalRecordKind.INSULIN_DOSES, dose)
            uow.commit()
        return recorded


@final
class RecordMealUseCase:
    """``POST /meals``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        writer: RecordWriter,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._writer = writer
        self._ids = ids
        self._clock = clock

    def execute(self, input: RecordInput[MealData]) -> RecordedRecord[Meal]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.RECORDS_WRITE_OWN)
            data = input.data
            meal = Meal(
                id=self._ids.new_id(),
                clinic_id=scope.clinic_id,
                patient_id=scope.patient_id,
                client_record_id=input.client_record_id or self._ids.new_id(),
                recorded_by=input.actor.user_id,
                received_at=self._clock.now(),
                eaten_at=data.eaten_at,
                meal_type=data.meal_type,
                carbs_g=data.carbs_g,
                note=data.note,
            )
            recorded = self._writer.write(uow, ClinicalRecordKind.MEALS, meal)
            uow.commit()
        return recorded


@final
class RecordActivityUseCase:
    """``POST /activities``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        writer: RecordWriter,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._writer = writer
        self._ids = ids
        self._clock = clock

    def execute(
        self, input: RecordInput[ActivityData]
    ) -> RecordedRecord[PhysicalActivity]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.RECORDS_WRITE_OWN)
            data = input.data
            activity = PhysicalActivity(
                id=self._ids.new_id(),
                clinic_id=scope.clinic_id,
                patient_id=scope.patient_id,
                client_record_id=input.client_record_id or self._ids.new_id(),
                recorded_by=input.actor.user_id,
                received_at=self._clock.now(),
                started_at=data.started_at,
                activity_type=data.activity_type,
                duration_min=data.duration_min,
                intensity=data.intensity,
                note=data.note,
            )
            recorded = self._writer.write(uow, ClinicalRecordKind.ACTIVITIES, activity)
            uow.commit()
        return recorded


@final
class RecordSymptomUseCase:
    """``POST /symptoms``: one symptom of the clinic catalog per record."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        writer: RecordWriter,
        catalog: SymptomCatalogPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._writer = writer
        self._catalog = catalog
        self._ids = ids
        self._clock = clock

    def execute(self, input: RecordInput[SymptomData]) -> RecordedRecord[Symptom]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.RECORDS_WRITE_OWN)
            data = input.data
            entry = self._catalog.find_active(scope.clinic_id, data.symptom_code)
            if entry is None:
                raise InsumapError(
                    ErrorCode.VALIDATION_ERROR,
                    detail={
                        "errors": [{"field": SYMPTOM_FIELD, "type": "unknown_symptom"}]
                    },
                )
            require_site_for(entry, data)
            symptom = Symptom(
                id=self._ids.new_id(),
                clinic_id=scope.clinic_id,
                patient_id=scope.patient_id,
                client_record_id=input.client_record_id or self._ids.new_id(),
                recorded_by=input.actor.user_id,
                received_at=self._clock.now(),
                symptom_at=data.occurred_at,
                symptom=entry,
                note=data.note,
                injection_site=data.injection_site,
            )
            recorded = self._writer.write(uow, ClinicalRecordKind.SYMPTOMS, symptom)
            uow.commit()
        return recorded


@final
class RecordOwnLabResultUseCase:
    """``POST /lab-results``: a self reported HbA1c."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        writer: RecordWriter,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._writer = writer
        self._ids = ids
        self._clock = clock

    def execute(self, input: RecordInput[LabData]) -> RecordedRecord[LabResult]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.LABS_WRITE_OWN)
            result = _lab_result(
                self._ids,
                self._clock,
                clinic_id=scope.clinic_id,
                patient_id=scope.patient_id,
                recorded_by=input.actor.user_id,
                data=input.data,
                origin=LabOrigin.PATIENT_REPORTED,
                client_record_id=input.client_record_id,
            )
            recorded = self._writer.write(uow, ClinicalRecordKind.LAB_RESULTS, result)
            uow.commit()
        return recorded


@final
class RecordPatientLabResultUseCase:
    """``POST /patients/{patient_id}/lab-results``: a doctor confirms an HbA1c."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: AssignedPatientGate,
        writer: RecordWriter,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._writer = writer
        self._ids = ids
        self._clock = clock

    def execute(self, input: AssignedLabInput) -> RecordedRecord[LabResult]:
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            patient_id = self._gate.enter(
                actor,
                PermissionCode.LABS_WRITE_ASSIGNED,
                input.patient_id,
                DataResource.LAB_RESULTS,
            )
            if actor.clinic_id is None:
                raise InsumapError(ErrorCode.FORBIDDEN)
            result = _lab_result(
                self._ids,
                self._clock,
                clinic_id=actor.clinic_id,
                patient_id=patient_id,
                recorded_by=actor.user_id,
                data=input.data,
                origin=LabOrigin.LAB,
                client_record_id=input.client_record_id,
            )
            recorded = self._writer.write(uow, ClinicalRecordKind.LAB_RESULTS, result)
            uow.commit()
        return recorded


def _lab_result(
    ids: IdGenerator,
    clock: Clock,
    *,
    clinic_id: UUID,
    patient_id: UUID,
    recorded_by: UUID,
    data: LabData,
    origin: LabOrigin,
    client_record_id: UUID | None,
) -> LabResult:
    return LabResult(
        id=ids.new_id(),
        clinic_id=clinic_id,
        patient_id=patient_id,
        client_record_id=client_record_id or ids.new_id(),
        recorded_by=recorded_by,
        received_at=clock.now(),
        test_code=HBA1C_TEST_CODE,
        performed_on=data.performed_on,
        value=data.value,
        unit=data.unit,
        value_pct=hba1c_to_percent(data.value, data.unit),
        origin=origin,
    )
