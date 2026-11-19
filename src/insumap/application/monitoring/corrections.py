"""Correct or annul a record with a new row that points at the original."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWorkPort,
)
from insumap.application.monitoring.data import (
    ActivityData,
    GlucoseData,
    InsulinData,
    MealData,
    RecordData,
    SymptomData,
)
from insumap.application.monitoring.gate import OwnPatientGate
from insumap.application.monitoring.glucose import GlucoseReadingRecorder
from insumap.application.monitoring.ports import (
    ClinicalRecordKind,
    ClinicalRecordPort,
    GlucoseReadingPort,
    SymptomCatalogPort,
)
from insumap.application.monitoring.records import require_site_for
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.glucose import GlucoseReading, GlucoseValue
from insumap.domain.monitoring.record import ClinicalRecord, RecordType
from insumap.domain.monitoring.records import (
    InsulinDose,
    Meal,
    PhysicalActivity,
    Symptom,
)
from insumap.domain.monitoring.validation import (
    GlucoseReadingValidationHandler,
    ReadingCandidate,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

KIND_BY_RECORD_TYPE: Final = {
    RecordType.INSULIN_DOSES: ClinicalRecordKind.INSULIN_DOSES,
    RecordType.MEALS: ClinicalRecordKind.MEALS,
    RecordType.ACTIVITIES: ClinicalRecordKind.ACTIVITIES,
    RecordType.SYMPTOMS: ClinicalRecordKind.SYMPTOMS,
}
CORRECTION_FIELD: Final = "body.correction"


def _wrong_data() -> InsumapError:
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"field": CORRECTION_FIELD, "type": "wrong_record_type"}]},
    )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectRecordInput:
    actor: Actor
    record_type: RecordType
    record_id: UUID
    reason: str | None
    data: RecordData


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AnnulRecordInput:
    actor: Actor
    record_type: RecordType
    record_id: UUID
    reason: str | None


@final
class CorrectRecordUseCase:
    """``POST /records/{record_type}/{record_id}/corrections``.

    The original is never touched: a new ``CORRECTION`` row points at it and the
    original shows as ``CORRECTED``. A corrected reading goes through the
    validation chain again.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        readings: GlucoseReadingPort,
        records: ClinicalRecordPort,
        catalog: SymptomCatalogPort,
        recorder: GlucoseReadingRecorder,
        chain: GlucoseReadingValidationHandler,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._readings = readings
        self._records = records
        self._catalog = catalog
        self._recorder = recorder
        self._chain = chain
        self._ids = ids
        self._clock = clock

    def execute(self, input: CorrectRecordInput) -> ClinicalRecord:
        """Save and return the correction row."""
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.RECORDS_CORRECT_OWN)
            original = _load(
                self._readings,
                self._records,
                input.record_type,
                scope.patient_id,
                input.record_id,
            )
            common: dict[str, Any] = {
                "new_id": self._ids.new_id(),
                "client_record_id": self._ids.new_id(),
                "reason": input.reason,
                "now": self._clock.now(),
                "recorded_by": input.actor.user_id,
            }
            if isinstance(original, GlucoseReading):
                fixed: ClinicalRecord = self._correct_reading(
                    original, input.data, common
                )
                self._readings.add(fixed)  # type: ignore[arg-type]
            else:
                fixed = self._correct_other(
                    original, input.data, common, scope.clinic_id
                )
                self._records.add(fixed)
            uow.commit()
        return fixed

    def _correct_reading(
        self, original: GlucoseReading, data: RecordData, common: dict[str, Any]
    ) -> GlucoseReading:
        if not isinstance(data, GlucoseData):
            raise _wrong_data()
        value = GlucoseValue.from_input(data.value, data.unit)
        params = self._recorder.load_params(original.clinic_id)
        issues = self._chain.validate(
            ReadingCandidate(
                value_mg_dl=value.mg_dl,
                measured_at=data.measured_at,
                now=common["now"],
                params=params,
                previous=self._readings.previous_before(
                    original.patient_id, data.measured_at, excluding=original.id
                ),
            )
        )
        fixed = original.corrected(
            **common,
            value_mg_dl=value.mg_dl,
            measured_at=data.measured_at,
            source=data.source,
            context=data.context,
            note=data.note,
        )
        return fixed.revalidated(issues)

    def _correct_other(
        self,
        original: ClinicalRecord,
        data: RecordData,
        common: dict[str, Any],
        clinic_id: UUID,
    ) -> ClinicalRecord:
        if isinstance(original, InsulinDose) and isinstance(data, InsulinData):
            return original.corrected(
                **common,
                administered_at=data.administered_at,
                insulin_kind=data.insulin_kind,
                product_name=data.product_name,
                units=data.units,
                note=data.note,
                injection_site=data.injection_site,
                injection_spot=data.injection_spot,
            )
        if isinstance(original, Meal) and isinstance(data, MealData):
            return original.corrected(
                **common,
                eaten_at=data.eaten_at,
                meal_type=data.meal_type,
                carbs_g=data.carbs_g,
                note=data.note,
            )
        if isinstance(original, PhysicalActivity) and isinstance(data, ActivityData):
            return original.corrected(
                **common,
                started_at=data.started_at,
                activity_type=data.activity_type,
                duration_min=data.duration_min,
                intensity=data.intensity,
                note=data.note,
            )
        if isinstance(original, Symptom) and isinstance(data, SymptomData):
            entry = self._catalog.find_active(clinic_id, data.symptom_code)
            if entry is None:
                raise _wrong_data()
            require_site_for(entry, data)
            return original.corrected(
                **common,
                symptom_at=data.occurred_at,
                symptom=entry,
                note=data.note,
                injection_site=data.injection_site,
            )
        raise _wrong_data()


@final
class AnnulRecordUseCase:
    """``POST /records/{record_type}/{record_id}/annulments``: annul, never delete."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        readings: GlucoseReadingPort,
        records: ClinicalRecordPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._readings = readings
        self._records = records
        self._ids = ids
        self._clock = clock

    def execute(self, input: AnnulRecordInput) -> ClinicalRecord:
        """Save and return the annulment row."""
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            scope = self._gate.enter(input.actor, PermissionCode.RECORDS_CORRECT_OWN)
            original = _load(
                self._readings,
                self._records,
                input.record_type,
                scope.patient_id,
                input.record_id,
            )
            voided = original.voided(
                new_id=self._ids.new_id(),
                client_record_id=self._ids.new_id(),
                reason=input.reason,
                now=self._clock.now(),
                recorded_by=input.actor.user_id,
            )
            if isinstance(voided, GlucoseReading):
                self._readings.add(voided)
            else:
                self._records.add(voided)
            uow.commit()
        return voided


def _load(
    readings: GlucoseReadingPort,
    records: ClinicalRecordPort,
    record_type: RecordType,
    patient_id: UUID,
    record_id: UUID,
) -> ClinicalRecord:
    """The record of the patient, or ``404`` (a stranger's record looks the same)."""
    found: ClinicalRecord | None
    if record_type is RecordType.READINGS:
        found = readings.get(patient_id, record_id)
    else:
        found = records.get(KIND_BY_RECORD_TYPE[record_type], patient_id, record_id)
    if found is None:
        raise InsumapError(ErrorCode.NOT_FOUND)
    return found
