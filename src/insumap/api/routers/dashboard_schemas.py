"""Response and request models of the dashboard, notes, overview and KPI endpoints.

Decimals leave the API as numbers and glucose as mg/dL, like the metrics and
records endpoints. Every model is explicit: nothing is returned by accident.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final, Self
from uuid import UUID

from pydantic import BaseModel, Field

from insumap.api.routers.auth_schemas import StrictRequest
from insumap.application.clinic_kpis.queries import ClinicKpis
from insumap.application.metrics.metrics import MetricWindow
from insumap.application.overview.patient_overview_facade import PatientOverview
from insumap.domain.alerts.alert import Alert
from insumap.domain.clinical_notes.note import ClinicalNote
from insumap.domain.dashboard.triage import TriageAssessment, TriageFlag
from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics
from insumap.domain.monitoring.glucose import GlucoseReading
from insumap.domain.monitoring.injection_sites import PregnancyStatus
from insumap.domain.onboarding.vocabulary import Sex
from insumap.domain.reminders.reminder import Reminder
from insumap.domain.treatment.plan import TreatmentPlan
from insumap.shared.field_limits import FieldLimits

SIMULATED_SOURCE: Final = "SIMULATED"
"""``data_source`` of the demo clinic (API.md 8.11, G6)."""


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


class TriageFlagResponse(BaseModel):
    """One reason the patient needs attention, with its text in Spanish."""

    code: TriageFlag
    reason: str = Field(description="Motivo legible en español.")


class TriageLastReadingResponse(BaseModel):
    value_mg_dl: float
    measured_at: datetime


class TriagePatientResponse(BaseModel):
    """One assigned patient in the triage list, most urgent first."""

    patient_id: UUID
    full_name: str
    risk_tier: str
    risk_score: int = Field(description="Número de banderas activas (provisional).")
    flags: list[TriageFlagResponse]
    open_alerts_count: int
    tir_pct: float | None
    last_reading: TriageLastReadingResponse | None
    reviewed_at: datetime | None
    reviewed: bool
    is_fallback: bool = Field(
        description="`true`: el orden usa reglas, no la IA (RiskScoringStrategy)."
    )
    simulated: bool


class ReviewedPatientResponse(BaseModel):
    patient_id: UUID
    reviewed_at: datetime
    window: MetricWindow


class ClinicalNoteRequest(StrictRequest):
    """A note in Spanish; ``corrects_note_id`` names the note it replaces."""

    text: str = Field(
        min_length=FieldLimits.CLINICAL_NOTE_BODY_MIN_LENGTH,
        max_length=FieldLimits.CLINICAL_NOTE_BODY_MAX_LENGTH,
        description="Texto de la nota. Una corrección es otra nota nueva.",
    )
    corrects_note_id: UUID | None = Field(
        default=None, description="Nota del mismo paciente que esta corrige."
    )


class ClinicalNoteResponse(BaseModel):
    id: UUID
    text: str
    author_id: UUID
    created_at: datetime
    corrects_note_id: UUID | None
    simulated: bool

    @classmethod
    def of(cls, note: ClinicalNote, *, simulated: bool) -> Self:
        return cls(
            id=note.id,
            text=note.body,
            author_id=note.author_user_id,
            created_at=note.created_at,
            corrects_note_id=note.supersedes_id,
            simulated=simulated,
        )


class RecentReadingResponse(BaseModel):
    id: UUID
    value_mg_dl: float
    measured_at: datetime
    source: str
    context: str | None

    @classmethod
    def of(cls, reading: GlucoseReading) -> Self:
        return cls(
            id=reading.id,
            value_mg_dl=float(reading.value_mg_dl),
            measured_at=reading.measured_at,
            source=reading.source.value,
            context=None if reading.context is None else reading.context.value,
        )


class TargetRangeResponse(BaseModel):
    profile_id: UUID
    profile_code: str
    profile_version: int
    range_low_mg_dl: float
    range_high_mg_dl: float
    strategy_code: str


class MetricsSummaryResponse(BaseModel):
    signal: str
    is_sufficient: bool
    data_sufficiency_pct: float
    tir_pct: float | None
    tbr_pct: float | None
    tar_pct: float | None
    cv_pct: float | None
    gmi_pct: float | None

    @classmethod
    def of(cls, metrics: GlycemicMetrics) -> Self:
        return cls(
            signal=metrics.signal.value,
            is_sufficient=metrics.is_sufficient,
            data_sufficiency_pct=float(metrics.data_sufficiency_pct),
            tir_pct=_number(metrics.tir_pct),
            tbr_pct=_number(metrics.tbr_pct),
            tar_pct=_number(metrics.tar_pct),
            cv_pct=_number(metrics.cv_pct),
            gmi_pct=_number(metrics.gmi_pct),
        )


class ActivePlanSummaryResponse(BaseModel):
    id: UUID
    version: int
    status: str
    activated_at: datetime | None
    items_count: int

    @classmethod
    def of(cls, plan: TreatmentPlan) -> Self:
        return cls(
            id=plan.plan_id,
            version=plan.version,
            status=plan.status.value,
            activated_at=plan.activated_at,
            items_count=len(plan.items),
        )


class OpenAlertResponse(BaseModel):
    id: UUID
    alert_type: str
    priority: str
    status: str
    opened_at: datetime

    @classmethod
    def of(cls, alert: Alert) -> Self:
        return cls(
            id=alert.alert_id,
            alert_type=alert.alert_type.value,
            priority=alert.priority.value,
            status=alert.status.value,
            opened_at=alert.opened_at,
        )


class ReminderResponse(BaseModel):
    id: UUID
    reminder_type: str
    local_time: str
    days_of_week: list[int] | None
    is_active: bool

    @classmethod
    def of(cls, reminder: Reminder) -> Self:
        return cls(
            id=reminder.id,
            reminder_type=reminder.reminder_type.value,
            local_time=reminder.schedule.local_time.isoformat(timespec="minutes"),
            days_of_week=None
            if reminder.schedule.days_of_week is None
            else list(reminder.schedule.days_of_week),
            is_active=reminder.is_active,
        )


class PatientOverviewResponse(BaseModel):
    """The start page of a patient: readings, metrics, plan, alerts and reminders."""

    patient_id: UUID
    window: MetricWindow
    period_from: datetime
    period_to: datetime
    timezone: str
    target: TargetRangeResponse
    on_target: bool | None
    metrics: MetricsSummaryResponse
    recent_readings: list[RecentReadingResponse]
    active_plan: ActivePlanSummaryResponse | None
    open_alerts_count: int
    open_alerts: list[OpenAlertResponse]
    reminders: list[ReminderResponse]
    simulated: bool
    data_source: str | None = Field(
        default=None, description="`SIMULATED` en la clínica demo; ausente si no."
    )
    sex: Sex = Field(
        description="Sexo administrativo: `FEMALE`, `MALE`, `OTHER` o `UNKNOWN`."
    )
    bmi: float | None = Field(description="IMC del paciente, o nulo si no se conoce.")
    pregnancy_status: PregnancyStatus = Field(
        description="`NONE`, `PREGNANT` o `UNKNOWN`."
    )

    @classmethod
    def of(cls, overview: PatientOverview) -> Self:
        profile = overview.profile
        return cls(
            patient_id=overview.patient_id,
            window=overview.window,
            period_from=overview.period_from,
            period_to=overview.period_to,
            timezone=overview.timezone,
            target=TargetRangeResponse(
                profile_id=profile.id,
                profile_code=profile.code,
                profile_version=profile.version,
                range_low_mg_dl=float(profile.range_low_mg_dl),
                range_high_mg_dl=float(profile.range_high_mg_dl),
                strategy_code=overview.strategy_code,
            ),
            on_target=overview.on_target,
            metrics=MetricsSummaryResponse.of(overview.metrics),
            recent_readings=[
                RecentReadingResponse.of(r) for r in overview.recent_readings
            ],
            active_plan=None
            if overview.active_plan is None
            else ActivePlanSummaryResponse.of(overview.active_plan),
            open_alerts_count=overview.open_alerts_count,
            open_alerts=[OpenAlertResponse.of(a) for a in overview.open_alerts],
            reminders=[ReminderResponse.of(r) for r in overview.reminders],
            simulated=overview.simulated,
            data_source=SIMULATED_SOURCE if overview.simulated else None,
            sex=overview.body.sex,
            bmi=_number(overview.body.bmi),
            pregnancy_status=overview.body.pregnancy_status,
        )


class ClinicKpisResponse(BaseModel):
    """Aggregates of the clinic: counts below the minimum cell are ``null``."""

    total_patients: int | None
    patients_by_status: dict[str, int | None]
    activation_rate_pct: float | None
    open_alerts: int | None
    escalated_alerts: int | None

    @classmethod
    def of(cls, kpis: ClinicKpis) -> Self:
        return cls(
            total_patients=kpis.total_patients,
            patients_by_status=kpis.patients_by_status,
            activation_rate_pct=_number(kpis.activation_rate_pct),
            open_alerts=kpis.open_alerts,
            escalated_alerts=kpis.escalated_alerts,
        )


def triage_patient(
    assessment: TriageAssessment, *, reasons: dict[TriageFlag, str], simulated: bool
) -> TriagePatientResponse:
    """The triage row of one patient; ``reasons`` maps each flag to its text."""
    return TriagePatientResponse(
        patient_id=assessment.patient_id,
        full_name=assessment.full_name,
        risk_tier=assessment.risk_tier.value,
        risk_score=assessment.score,
        flags=[
            TriageFlagResponse(code=flag, reason=reasons[flag])
            for flag in assessment.flags
        ],
        open_alerts_count=assessment.open_alerts_count,
        tir_pct=_number(assessment.tir_pct),
        last_reading=None
        if assessment.last_reading_at is None or assessment.last_reading_mg_dl is None
        else TriageLastReadingResponse(
            value_mg_dl=float(assessment.last_reading_mg_dl),
            measured_at=assessment.last_reading_at,
        ),
        reviewed_at=assessment.reviewed_at,
        reviewed=assessment.reviewed,
        is_fallback=True,
        simulated=simulated,
    )
