"""Requests and responses of the patient record endpoints."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from insumap.application.monitoring.data import (
    ActivityData,
    GlucoseData,
    InsulinData,
    LabData,
    MealData,
    RecordData,
    SymptomData,
)
from insumap.application.monitoring.glucose import (
    BatchItemResult,
    CgmImportResult,
    RecordOutcome,
)
from insumap.domain.monitoring.glucose import (
    GlucoseReading,
    GlucoseUnit,
    ReadingContext,
    ReadingSource,
)
from insumap.domain.monitoring.injection_sites import SiteCode
from insumap.domain.monitoring.record import ClinicalRecord, EntryType
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
)
from insumap.domain.monitoring.timeline import TimelineItem
from insumap.shared.errors import ErrorCode
from insumap.shared.field_limits import FieldLimits

GLUCOSE_DECIMALS = 1
UNITS_DECIMALS = 2
CARBS_DECIMALS = 1
LAB_DECIMALS = 2

NoteInput = Annotated[
    str | None,
    Field(
        default=None,
        max_length=FieldLimits.RECORD_NOTE_MAX_LENGTH,
        description="Nota breve del paciente (texto libre acotado).",
    ),
]
ClientRecordId = Annotated[
    UUID | None,
    Field(
        default=None,
        description=(
            "UUID generado por la app para que repetir el envío no duplique. Si "
            "falta, el servidor genera uno."
        ),
    ),
]


class StrictRequest(BaseModel):
    """Base of every body: unknown fields answer ``422``."""

    model_config = ConfigDict(extra="forbid")


class RecordFields(StrictRequest):
    """The values of a record that can be corrected; each type turns them to data."""

    def to_data(self) -> RecordData:
        """The typed values of this record type."""
        raise NotImplementedError


class GlucoseFields(RecordFields):
    """Los valores de una lectura de glucosa."""

    value: Decimal = Field(
        gt=0,
        le=FieldLimits.GLUCOSE_VALUE_INPUT_MAX,
        description="Valor medido, en la unidad indicada.",
        examples=["112"],
    )
    unit: GlucoseUnit = Field(description="Unidad del valor: `mg/dL` o `mmol/L`.")
    measured_at: AwareDatetime = Field(description="Momento de la medición con zona.")
    source: ReadingSource = Field(description="`MANUAL`, `SMBG` o `CGM`.")
    context: ReadingContext | None = Field(
        default=None,
        description="Contexto: ayunas, antes o después de comer, al acostarse, "
        "ejercicio u otro.",
    )
    note: str | None = Field(
        default=None, max_length=FieldLimits.GLUCOSE_NOTE_MAX_LENGTH
    )

    def to_data(self) -> GlucoseData:
        return GlucoseData(
            value=self.value,
            unit=self.unit,
            measured_at=self.measured_at,
            source=self.source,
            context=self.context,
            note=self.note,
        )


class RecordGlucoseReadingRequest(GlucoseFields):
    """Una lectura de glucosa del paciente."""

    client_reading_id: UUID = Field(
        description="UUID generado por la app; hace idempotente el envío."
    )


class RecordGlucoseReadingsBatchRequest(StrictRequest):
    """La cola sin conexión: hasta 500 lecturas."""

    items: list[RecordGlucoseReadingRequest] = Field(
        min_length=1, max_length=FieldLimits.READINGS_BATCH_MAX_ITEMS
    )


class InsulinFields(RecordFields):
    """Los valores de una dosis de insulina que el paciente indica."""

    kind: InsulinKind = Field(description="`BASAL`, `BOLUS`, `CORRECTION` o `MIXED`.")
    product_name: str = Field(
        min_length=1, max_length=FieldLimits.INSULIN_PRODUCT_NAME_MAX_LENGTH
    )
    units: Decimal = Field(
        gt=0,
        le=FieldLimits.INSULIN_UNITS_INPUT_MAX,
        decimal_places=UNITS_DECIMALS,
        description="Unidades que el paciente dice haberse aplicado.",
    )
    administered_at: AwareDatetime
    note: NoteInput = None
    injection_site: SiteCode | None = Field(
        default=None,
        description="Sitio donde se aplicó la dosis; opcional. Los códigos son los "
        "de `GET /patients/own/injection-sites`.",
    )
    injection_spot: int | None = Field(
        default=None,
        ge=FieldLimits.INJECTION_SPOT_MIN,
        le=FieldLimits.INJECTION_SPOT_MAX,
        description="Punto dentro del sitio, de 1 a 4. Exige `injection_site`.",
    )

    @model_validator(mode="after")
    def _spot_needs_a_site(self) -> Self:
        if self.injection_spot is not None and self.injection_site is None:
            raise ValueError("injection_spot requires injection_site")
        return self

    def to_data(self) -> InsulinData:
        return InsulinData(
            administered_at=self.administered_at,
            insulin_kind=self.kind,
            product_name=self.product_name,
            units=self.units,
            note=self.note,
            injection_site=self.injection_site,
            injection_spot=self.injection_spot,
        )


class RecordInsulinDoseRequest(InsulinFields):
    """Una dosis de insulina. La API nunca calcula ni sugiere una dosis."""

    client_record_id: ClientRecordId = None


class MealFields(RecordFields):
    meal_type: MealType
    eaten_at: AwareDatetime
    carbs_g: Decimal = Field(
        ge=0,
        le=FieldLimits.CARBS_G_INPUT_MAX,
        decimal_places=CARBS_DECIMALS,
        description="Carbohidratos estimados, en gramos.",
    )
    note: NoteInput = None

    def to_data(self) -> MealData:
        return MealData(
            eaten_at=self.eaten_at,
            meal_type=self.meal_type,
            carbs_g=self.carbs_g,
            note=self.note,
        )


class RecordMealRequest(MealFields):
    """Una comida con carbohidratos estimados."""

    client_record_id: ClientRecordId = None


class ActivityFields(RecordFields):
    activity_type: str = Field(
        min_length=1, max_length=FieldLimits.ACTIVITY_TYPE_MAX_LENGTH
    )
    intensity: ActivityIntensity
    duration_minutes: int = Field(ge=1, le=FieldLimits.ACTIVITY_DURATION_MINUTES_MAX)
    started_at: AwareDatetime
    note: NoteInput = None

    def to_data(self) -> ActivityData:
        return ActivityData(
            started_at=self.started_at,
            activity_type=self.activity_type,
            duration_min=self.duration_minutes,
            intensity=self.intensity,
            note=self.note,
        )


class RecordActivityRequest(ActivityFields):
    """Una actividad física."""

    client_record_id: ClientRecordId = None


class SymptomFields(RecordFields):
    symptom_code: str = Field(
        min_length=1,
        max_length=FieldLimits.SYMPTOM_CODE_MAX_LENGTH,
        description="Código de un síntoma del catálogo de la clínica.",
        examples=["THIRST"],
    )
    occurred_at: AwareDatetime
    note: NoteInput = None

    def to_data(self) -> SymptomData:
        return SymptomData(
            symptom_code=self.symptom_code,
            occurred_at=self.occurred_at,
            note=self.note,
        )


class RecordSymptomRequest(SymptomFields):
    """Un síntoma del catálogo (uno por registro)."""

    client_record_id: ClientRecordId = None


class RecordLabResultRequest(StrictRequest):
    """Un resultado de HbA1c."""

    value: Decimal = Field(
        gt=0,
        le=FieldLimits.LAB_VALUE_INPUT_MAX,
        decimal_places=LAB_DECIMALS,
        description="Valor en la unidad indicada.",
    )
    unit: LabUnit = Field(description="`%` o `mmol/mol` (se convierte con IFCC-NGSP).")
    measured_on: date = Field(description="Fecha del examen.")
    client_record_id: ClientRecordId = None

    def to_data(self, origin: LabOrigin) -> LabData:
        return LabData(
            value=self.value,
            unit=self.unit,
            performed_on=self.measured_on,
            origin=origin,
        )


class CorrectRecordRequest(StrictRequest):
    """La corrección de un registro propio: motivo y los valores nuevos."""

    reason: str | None = Field(
        default=None,
        description="Motivo de 10 a 500 caracteres (`REASON_REQUIRED` si no cumple).",
    )
    correction: dict[str, JsonValue] = Field(
        description="Los campos del mismo tipo de registro, completos."
    )


class AnnulRecordRequest(StrictRequest):
    """La anulación de un registro propio: solo el motivo."""

    reason: str | None = Field(
        default=None,
        description="Motivo de 10 a 500 caracteres (`REASON_REQUIRED` si no cumple).",
    )


class RecordResponse(BaseModel):
    """Campos comunes de un registro."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    client_record_id: UUID
    status: str = Field(
        description="`ACTIVE` (o `ACCEPTED`/`FLAGGED` en glucosa), `CORRECTED` o "
        "`VOIDED` si otra fila lo reemplazó."
    )
    entry_type: EntryType = Field(description="`ORIGINAL`, `CORRECTION` o `VOID`.")
    supersedes_id: UUID | None = Field(
        description="Fila original que esta fila corrige o anula."
    )
    simulated: bool = Field(description="`true` si la clínica es de datos simulados.")


def _common(record: ClinicalRecord, *, simulated: bool) -> dict[str, object]:
    return {
        "id": record.id,
        "client_record_id": record.client_record_id,
        "status": record.display_status,
        "entry_type": record.entry_type,
        "supersedes_id": record.supersedes_id,
        "simulated": simulated,
    }


class GlucoseReadingResponse(RecordResponse):
    client_reading_id: UUID
    value_mg_dl: float = Field(description="Siempre en mg/dL.")
    measured_at: datetime
    source: ReadingSource
    context: ReadingContext | None
    note: str | None
    issue_codes: list[str] = Field(
        description="`DUPLICATE_SUSPECTED`, `IMPLAUSIBLE_RATE_OF_CHANGE` o "
        "`UNIT_MISMATCH_SUSPECTED`."
    )

    @classmethod
    def of(cls, reading: GlucoseReading, *, simulated: bool) -> GlucoseReadingResponse:
        return cls(
            **_common(reading, simulated=simulated),  # type: ignore[arg-type]
            client_reading_id=reading.client_record_id,
            value_mg_dl=float(reading.value_mg_dl),
            measured_at=reading.measured_at,
            source=reading.source,
            context=reading.context,
            note=reading.note,
            issue_codes=[issue.value for issue in reading.issues],
        )


class InsulinDoseResponse(RecordResponse):
    kind: InsulinKind
    product_name: str
    units: float
    administered_at: datetime
    treatment_plan_id: UUID | None
    note: str | None
    injection_site: SiteCode | None
    injection_spot: int | None

    @classmethod
    def of(cls, dose: InsulinDose, *, simulated: bool) -> InsulinDoseResponse:
        return cls(
            **_common(dose, simulated=simulated),  # type: ignore[arg-type]
            kind=dose.insulin_kind,
            product_name=dose.product_name,
            units=float(dose.units),
            administered_at=dose.administered_at,
            treatment_plan_id=dose.plan_id,
            note=dose.note,
            injection_site=dose.injection_site,
            injection_spot=dose.injection_spot,
        )


class MealResponse(RecordResponse):
    meal_type: MealType
    eaten_at: datetime
    carbs_g: float
    note: str | None

    @classmethod
    def of(cls, meal: Meal, *, simulated: bool) -> MealResponse:
        return cls(
            **_common(meal, simulated=simulated),  # type: ignore[arg-type]
            meal_type=meal.meal_type,
            eaten_at=meal.eaten_at,
            carbs_g=float(meal.carbs_g),
            note=meal.note,
        )


class ActivityResponse(RecordResponse):
    activity_type: str
    intensity: ActivityIntensity
    duration_minutes: int
    started_at: datetime
    note: str | None

    @classmethod
    def of(cls, activity: PhysicalActivity, *, simulated: bool) -> ActivityResponse:
        return cls(
            **_common(activity, simulated=simulated),  # type: ignore[arg-type]
            activity_type=activity.activity_type,
            intensity=activity.intensity,
            duration_minutes=activity.duration_min,
            started_at=activity.started_at,
            note=activity.note,
        )


class SymptomResponse(RecordResponse):
    symptom_code: str
    occurred_at: datetime
    alarm_detected: bool = Field(
        description="`true` si el síntoma es de alarma: la app muestra "
        '"contacta a tu equipo o a urgencias".'
    )
    note: str | None

    @classmethod
    def of(cls, symptom: Symptom, *, simulated: bool) -> SymptomResponse:
        return cls(
            **_common(symptom, simulated=simulated),  # type: ignore[arg-type]
            symptom_code=symptom.symptom.code,
            occurred_at=symptom.symptom_at,
            alarm_detected=symptom.symptom.is_alarm,
            note=symptom.note,
        )


class LabResultResponse(RecordResponse):
    value_percent: float = Field(description="HbA1c en %, normalizada con NGSP.")
    value: float
    unit: LabUnit
    measured_on: date
    origin: LabOrigin

    @classmethod
    def of(cls, lab: LabResult, *, simulated: bool) -> LabResultResponse:
        return cls(
            **_common(lab, simulated=simulated),  # type: ignore[arg-type]
            value_percent=float(lab.value_pct),
            value=float(lab.value),
            unit=lab.unit,
            measured_on=lab.performed_on,
            origin=lab.origin,
        )


class GlucoseReadingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[GlucoseReadingResponse]
    next_cursor: str | None


class InsulinDoseListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[InsulinDoseResponse]
    next_cursor: str | None


class MealListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MealResponse]
    next_cursor: str | None


class ActivityListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ActivityResponse]
    next_cursor: str | None


class SymptomListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SymptomResponse]
    next_cursor: str | None


class LabResultListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LabResultResponse]
    next_cursor: str | None


class BatchItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_reading_id: UUID
    result: RecordOutcome = Field(description="`CREATED`, `DUPLICATE` o `REJECTED`.")
    reading_id: UUID | None = Field(description="La lectura guardada, si se guardó.")
    reason_code: ErrorCode | None = Field(
        description="Código de la validación si se rechazó."
    )

    @classmethod
    def of(cls, result: BatchItemResult) -> BatchItemResponse:
        return cls(
            client_reading_id=result.client_reading_id,
            result=result.outcome,
            reading_id=result.reading_id,
            reason_code=result.reason_code,
        )


class BatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BatchItemResponse] = Field(description="Mismo orden que la solicitud.")


class CgmImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = Field(description="Formato de sensor reconocido.")
    created: int
    duplicates: int
    rejected: int

    @classmethod
    def of(cls, result: CgmImportResult) -> CgmImportResponse:
        return cls(
            format=result.format,
            created=result.created,
            duplicates=result.duplicates,
            rejected=result.rejected,
        )


class TimelineItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    event_type: str = Field(
        description="`GLUCOSE`, `INSULIN`, `MEAL`, `ACTIVITY` o `SYMPTOM`."
    )
    occurred_at: datetime
    status: str
    entry_type: EntryType
    data: dict[str, str | int | float | bool | None] = Field(
        description="Datos propios del tipo de evento (sin notas)."
    )

    @classmethod
    def of(cls, item: TimelineItem) -> TimelineItemResponse:
        return cls(
            id=item.id,
            event_type=item.event_type.value,
            occurred_at=item.occurred_at,
            status=item.status,
            entry_type=item.entry_type,
            data=dict(item.data),
        )


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TimelineItemResponse]
    next_cursor: str | None
    simulated: bool
