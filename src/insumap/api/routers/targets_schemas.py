"""Request and response models of the goals and reminders (API.md 8.7).

Requests are ``extra="forbid"``. Technical bounds come from ``FieldLimits``; the
clinical values are free numbers here and the domain checks their relations
(ranges ordered and so on) against the database rules.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from insumap.api.routers.common import StrictRequest
from insumap.application.targets.commands import AssignedTargetProfile
from insumap.domain.metrics.target_profile_version import (
    TargetProfileValues,
    TargetProfileVersion,
)
from insumap.domain.reminders.reminder import (
    LAST_WEEKDAY,
    Reminder,
    ReminderSchedule,
    ReminderType,
)
from insumap.shared.field_limits import FieldLimits

PERCENT_MAX: Final = 100
"""Upper bound of a percentage (the column allows more; the metric does not)."""

REASON_DESCRIPTION: Final = (
    "Motivo del cambio de la versión (queda en la auditoría y en el historial)."
)
CHANGE_REASON_MIN: Final = FieldLimits.REASON_MIN_LENGTH
CHANGE_REASON_MAX: Final = FieldLimits.REASON_MAX_LENGTH
NULLABLE_GOALS: Final = frozenset(
    {
        "hba1c_goal_pct",
        "fasting_low_mg_dl",
        "fasting_high_mg_dl",
        "postprandial_max_mg_dl",
        "postprandial_1h_max_mg_dl",
        "postprandial_2h_max_mg_dl",
    }
)
"""The goals that a profile may leave empty (the database allows a null)."""


class ProfilePopulation(StrEnum):
    """Population a profile applies to (``ck_target_profiles_population``)."""

    ADULT = "ADULT"
    OLDER_OR_HIGH_RISK = "OLDER_OR_HIGH_RISK"
    PREGNANCY_T1D = "PREGNANCY_T1D"
    PREGNANCY_T2D_GDM = "PREGNANCY_T2D_GDM"


def _mg_dl(description: str) -> Any:
    """A glucose threshold in mg/dL: ``numeric(5,1)``, positive."""
    return Field(
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
        description=description,
    )


def _percent(description: str) -> Any:
    """A percentage: between 0 and 100 (``numeric(5,2)``)."""
    return Field(
        ge=0,
        le=PERCENT_MAX,
        max_digits=5,
        decimal_places=2,
        description=description,
    )


def _count(description: str, *, ceiling: int = FieldLimits.INTEGER_MAX) -> Any:
    """A positive count, within the ``integer`` or ``smallint`` column it maps to."""
    return Field(gt=0, le=ceiling, description=description)


class TargetProfileValuesRequest(StrictRequest):
    """Every editable value of a profile. The metric names are those of the doc 7.5."""

    label: str = Field(
        min_length=1,
        max_length=FieldLimits.PROFILE_LABEL_MAX_LENGTH,
        description="Etiqueta visible en español.",
    )
    population: ProfilePopulation
    is_default: bool = Field(
        default=False,
        description="Perfil por defecto de su población en la clínica.",
    )
    range_low_mg_dl: Decimal = _mg_dl("Límite inferior del rango objetivo.")
    range_high_mg_dl: Decimal = _mg_dl("Límite superior del rango objetivo.")
    very_low_mg_dl: Decimal = _mg_dl("Umbral de hipoglucemia de nivel 2.")
    very_high_mg_dl: Decimal = _mg_dl("Umbral de hiperglucemia de nivel 2.")
    tir_min_pct: Decimal = _percent("Meta mínima de tiempo en rango.")
    tbr_l1_max_pct: Decimal = _percent("Máximo de tiempo bajo el rango (total).")
    tbr_l2_max_pct: Decimal = _percent("Máximo de tiempo bajo el umbral de nivel 2.")
    tar_l1_max_pct: Decimal = _percent("Máximo de tiempo sobre el rango (total).")
    tar_l2_max_pct: Decimal = _percent("Máximo de tiempo sobre el umbral de nivel 2.")
    cv_max_pct: Decimal = _percent("Máximo del coeficiente de variación.")
    min_data_sufficiency_pct: Decimal = _percent(
        "Suficiencia mínima de datos para reportar métricas."
    )
    min_days: int = _count(
        "Días del periodo de referencia.", ceiling=FieldLimits.SMALLINT_MAX
    )
    max_gap_minutes: int = _count(
        "Minutos máximos que una lectura representa.",
        ceiling=FieldLimits.SMALLINT_MAX,
    )
    hypo_episode_min_minutes: int = _count(
        "Minutos consecutivos bajo el umbral para contar un episodio.",
        ceiling=FieldLimits.SMALLINT_MAX,
    )
    min_readings_for_cv: int = _count("Lecturas mínimas para el CV con CGM.")
    min_readings_for_cv_smbg: int = _count(
        "Lecturas mínimas para el CV con glucometría."
    )
    night_start: time = Field(description="Inicio de la ventana nocturna (hora local).")
    night_end: time = Field(description="Fin de la ventana nocturna (hora local).")
    source_reference: str = Field(
        min_length=1,
        max_length=FieldLimits.SOURCE_REFERENCE_MAX_LENGTH,
        description="Fuente de los valores (consenso, guía y tabla).",
    )
    hba1c_goal_pct: Decimal | None = Field(
        default=None, gt=0, le=PERCENT_MAX, max_digits=4, decimal_places=1
    )
    fasting_low_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    fasting_high_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    postprandial_max_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    postprandial_1h_max_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    postprandial_2h_max_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )

    def to_values(self) -> TargetProfileValues:
        """The domain values of this request (``code`` is not one of them)."""
        names = {f.name for f in fields(TargetProfileValues)}
        data = self.model_dump(include=names)
        data["population"] = self.population.value
        return TargetProfileValues(**data)


class TargetProfileCreateRequest(TargetProfileValuesRequest):
    """A profile of the clinic: its code and its values (version 1, active at once)."""

    code: str = Field(
        min_length=1,
        max_length=FieldLimits.TARGET_PROFILE_CODE_MAX_LENGTH,
        pattern=FieldLimits.TARGET_PROFILE_CODE_PATTERN,
        description="Código del perfil en mayúsculas (por ejemplo CLINIC_TARGETS).",
    )


class TargetProfileVersionRequest(StrictRequest):
    """The values that change in a new version; the others are copied."""

    label: str | None = Field(
        default=None, min_length=1, max_length=FieldLimits.PROFILE_LABEL_MAX_LENGTH
    )
    population: ProfilePopulation | None = None
    is_default: bool | None = None
    range_low_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    range_high_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    very_low_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    very_high_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    tir_min_pct: Decimal | None = Field(
        default=None, ge=0, le=PERCENT_MAX, max_digits=5, decimal_places=2
    )
    tbr_l1_max_pct: Decimal | None = Field(
        default=None, ge=0, le=PERCENT_MAX, max_digits=5, decimal_places=2
    )
    tbr_l2_max_pct: Decimal | None = Field(
        default=None, ge=0, le=PERCENT_MAX, max_digits=5, decimal_places=2
    )
    tar_l1_max_pct: Decimal | None = Field(
        default=None, ge=0, le=PERCENT_MAX, max_digits=5, decimal_places=2
    )
    tar_l2_max_pct: Decimal | None = Field(
        default=None, ge=0, le=PERCENT_MAX, max_digits=5, decimal_places=2
    )
    cv_max_pct: Decimal | None = Field(
        default=None, ge=0, le=PERCENT_MAX, max_digits=5, decimal_places=2
    )
    min_data_sufficiency_pct: Decimal | None = Field(
        default=None, ge=0, le=PERCENT_MAX, max_digits=5, decimal_places=2
    )
    min_days: int | None = Field(default=None, gt=0, le=FieldLimits.SMALLINT_MAX)
    max_gap_minutes: int | None = Field(default=None, gt=0, le=FieldLimits.SMALLINT_MAX)
    hypo_episode_min_minutes: int | None = Field(
        default=None, gt=0, le=FieldLimits.SMALLINT_MAX
    )
    min_readings_for_cv: int | None = Field(
        default=None, gt=0, le=FieldLimits.INTEGER_MAX
    )
    min_readings_for_cv_smbg: int | None = Field(
        default=None, gt=0, le=FieldLimits.INTEGER_MAX
    )
    night_start: time | None = None
    night_end: time | None = None
    source_reference: str | None = Field(
        default=None, min_length=1, max_length=FieldLimits.SOURCE_REFERENCE_MAX_LENGTH
    )
    hba1c_goal_pct: Decimal | None = Field(
        default=None, gt=0, le=PERCENT_MAX, max_digits=4, decimal_places=1
    )
    fasting_low_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    fasting_high_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    postprandial_max_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    postprandial_1h_max_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    postprandial_2h_max_mg_dl: Decimal | None = Field(
        default=None,
        gt=0,
        le=FieldLimits.TARGET_MG_DL_MAX,
        max_digits=5,
        decimal_places=1,
    )
    change_reason: str = Field(
        min_length=CHANGE_REASON_MIN,
        max_length=CHANGE_REASON_MAX,
        description=REASON_DESCRIPTION,
    )

    @model_validator(mode="after")
    def _valid_changes(self) -> Self:
        """At least one value changes, and only the optional goals may be cleared."""
        changed = self.model_fields_set - {"change_reason"}
        if not changed:
            raise ValueError("Indica al menos un valor que cambia.")
        cleared = {n for n in changed if getattr(self, n) is None}
        if cleared - NULLABLE_GOALS:
            raise ValueError("Este valor no admite un nulo.")
        return self

    def changes(self) -> dict[str, Any]:
        """The fields the request set, as domain values (enums become their value)."""
        result: dict[str, Any] = {}
        for name in self.model_fields_set - {"change_reason"}:
            value = getattr(self, name)
            result[name] = (
                value.value if isinstance(value, ProfilePopulation) else value
            )
        return result


class TargetProfileAssignRequest(StrictRequest):
    """The profile to assign to the patient (a current one)."""

    target_profile_id: UUID = Field(
        description="Perfil vigente de la clínica o semilla."
    )


class TargetProfileVersionSummary(BaseModel):
    """One entry of the history of a profile."""

    id: UUID
    version: int
    status: str
    change_reason: str | None
    created_at: datetime
    activated_at: datetime | None

    @classmethod
    def of(cls, version: TargetProfileVersion) -> Self:
        return cls(
            id=version.id,
            version=version.version,
            status=version.status,
            change_reason=version.change_reason,
            created_at=version.created_at,
            activated_at=version.activated_at,
        )


class TargetProfileResponse(BaseModel):
    """A profile version with every value the metrics use."""

    id: UUID
    code: str
    label: str
    population: str
    version: int
    status: str
    is_default: bool
    range_low_mg_dl: float
    range_high_mg_dl: float
    very_low_mg_dl: float
    very_high_mg_dl: float
    tir_min_pct: float
    tbr_l1_max_pct: float
    tbr_l2_max_pct: float
    tar_l1_max_pct: float
    tar_l2_max_pct: float
    cv_max_pct: float
    min_data_sufficiency_pct: float
    min_days: int
    max_gap_minutes: int
    hypo_episode_min_minutes: int
    min_readings_for_cv: int
    min_readings_for_cv_smbg: int
    night_start: time
    night_end: time
    source_reference: str
    hba1c_goal_pct: float | None
    fasting_low_mg_dl: float | None
    fasting_high_mg_dl: float | None
    postprandial_max_mg_dl: float | None
    postprandial_1h_max_mg_dl: float | None
    postprandial_2h_max_mg_dl: float | None
    change_reason: str | None
    created_at: datetime
    activated_at: datetime | None

    @classmethod
    def of(cls, version: TargetProfileVersion) -> Self:
        v = version.values
        return cls(
            id=version.id,
            code=version.code,
            label=v.label,
            population=v.population,
            version=version.version,
            status=version.status,
            is_default=v.is_default,
            range_low_mg_dl=float(v.range_low_mg_dl),
            range_high_mg_dl=float(v.range_high_mg_dl),
            very_low_mg_dl=float(v.very_low_mg_dl),
            very_high_mg_dl=float(v.very_high_mg_dl),
            tir_min_pct=float(v.tir_min_pct),
            tbr_l1_max_pct=float(v.tbr_l1_max_pct),
            tbr_l2_max_pct=float(v.tbr_l2_max_pct),
            tar_l1_max_pct=float(v.tar_l1_max_pct),
            tar_l2_max_pct=float(v.tar_l2_max_pct),
            cv_max_pct=float(v.cv_max_pct),
            min_data_sufficiency_pct=float(v.min_data_sufficiency_pct),
            min_days=v.min_days,
            max_gap_minutes=v.max_gap_minutes,
            hypo_episode_min_minutes=v.hypo_episode_min_minutes,
            min_readings_for_cv=v.min_readings_for_cv,
            min_readings_for_cv_smbg=v.min_readings_for_cv_smbg,
            night_start=v.night_start,
            night_end=v.night_end,
            source_reference=v.source_reference,
            hba1c_goal_pct=_number(v.hba1c_goal_pct),
            fasting_low_mg_dl=_number(v.fasting_low_mg_dl),
            fasting_high_mg_dl=_number(v.fasting_high_mg_dl),
            postprandial_max_mg_dl=_number(v.postprandial_max_mg_dl),
            postprandial_1h_max_mg_dl=_number(v.postprandial_1h_max_mg_dl),
            postprandial_2h_max_mg_dl=_number(v.postprandial_2h_max_mg_dl),
            change_reason=version.change_reason,
            created_at=version.created_at,
            activated_at=version.activated_at,
        )


class TargetProfileDetailResponse(TargetProfileResponse):
    """A profile with the history of its versions, the current one included."""

    versions: list[TargetProfileVersionSummary]


class PatientTargetAssignmentResponse(BaseModel):
    """The profile assigned to a patient, with the version it points to."""

    id: UUID
    patient_id: UUID
    target_profile_id: UUID
    code: str
    version: int
    label: str
    assigned_at: datetime

    @classmethod
    def of(cls, result: AssignedTargetProfile) -> Self:
        assignment, profile = result.assignment, result.profile
        return cls(
            id=assignment.id,
            patient_id=assignment.patient_id,
            target_profile_id=assignment.target_profile_id,
            code=profile.code,
            version=profile.version,
            label=profile.values.label,
            assigned_at=assignment.assigned_at,
        )


class ScheduleRequest(StrictRequest):
    """A local time and its weekdays (1 Monday to 7 Sunday; none: every day)."""

    local_time: time = Field(description="Hora local de la clínica.")
    days_of_week: list[int] | None = Field(
        default=None,
        max_length=LAST_WEEKDAY,
        description="Días ISO (1 lunes a 7 domingo). Sin valor, todos los días.",
    )

    def to_schedule(self) -> ReminderSchedule:
        days = None if self.days_of_week is None else tuple(self.days_of_week)
        return ReminderSchedule(local_time=self.local_time, days_of_week=days)


class ReminderCreateRequest(StrictRequest):
    """A reminder of the patient, scheduled by his doctor."""

    reminder_type: ReminderType
    schedule: ScheduleRequest
    is_active: bool = Field(default=True)


class ReminderUpdateRequest(StrictRequest):
    """The fields to change; at least one of them."""

    schedule: ScheduleRequest | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _at_least_one_change(self) -> Self:
        if self.schedule is None and self.is_active is None:
            raise ValueError("Indica al menos un campo que cambia.")
        return self


class ReminderScheduleResponse(BaseModel):
    local_time: time
    days_of_week: list[int] | None


class ReminderResponse(BaseModel):
    """One reminder of a patient."""

    id: UUID
    patient_id: UUID
    reminder_type: ReminderType
    schedule: ReminderScheduleResponse
    is_active: bool
    message_key: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, reminder: Reminder) -> Self:
        days = reminder.schedule.days_of_week
        return cls(
            id=reminder.id,
            patient_id=reminder.patient_id,
            reminder_type=reminder.reminder_type,
            schedule=ReminderScheduleResponse(
                local_time=reminder.schedule.local_time,
                days_of_week=None if days is None else list(days),
            ),
            is_active=reminder.is_active,
            message_key=reminder.message_key,
            created_at=reminder.created_at,
            updated_at=reminder.updated_at,
        )


def _number(value: Decimal | None) -> float | None:
    """Decimals leave the API as numbers, as the metrics endpoints do."""
    return None if value is None else float(value)
