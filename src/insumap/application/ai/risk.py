"""``GET /patients/{patient_id}/risk``: the risk of deterioration of an assigned
patient (IA2).

The use case reads the window of the patient inside the doctor's transaction (the
assignment check and the audit row), commits it, and only then calls the proxy,
so the AI call never runs inside the read transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import final
from uuid import UUID
from zoneinfo import ZoneInfo

from insumap.application.access.ports import DataResource
from insumap.application.ai.assessments import (
    RiskAssessmentPort,
    RiskRequest,
    RiskResult,
)
from insumap.application.ai.records import PatientAiProfilePort
from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.metrics.metrics import (
    MIDNIGHT,
    MetricsPeriod,
    metrics_for,
    previous_period,
)
from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.ai.risk import RiskFeatures, RiskLimits
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics
from insumap.domain.metrics.target_profile import TargetProfile
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

READ_PERMISSION = PermissionCode.AI_RISK_READ_ASSIGNED


def window_period(days: int, now: datetime, zone: ZoneInfo) -> MetricsPeriod:
    """The ``days`` whole local days that end at the start of today (as the metrics)."""
    today = now.astimezone(zone).date()
    return MetricsPeriod(
        start=datetime.combine(today - timedelta(days=days), MIDNIGHT, zone),
        end=datetime.combine(today, MIDNIGHT, zone),
        zone=zone,
        days=days,
    )


def features_of(
    current: GlycemicMetrics, previous: GlycemicMetrics | None
) -> RiskFeatures:
    """The window's figures the rules and the AI read (Contrato-IA 8.2)."""
    delta: Decimal | None = None
    if (
        previous is not None
        and current.tir_pct is not None
        and previous.tir_pct is not None
    ):
        delta = current.tir_pct - previous.tir_pct
    return RiskFeatures(
        data_sufficiency_pct=current.data_sufficiency_pct,
        tir_pct=current.tir_pct,
        tbr_l1_pct=current.tbr_l1_pct,
        tbr_l2_pct=current.tbr_l2_pct,
        tar_l1_pct=current.tar_l1_pct,
        tar_l2_pct=current.tar_l2_pct,
        cv_pct=current.cv_pct,
        mean_glucose_mg_dl=current.mean_glucose_mg_dl,
        gmi_pct=current.gmi_pct,
        hypo_events_count=current.hypo_events_count,
        tir_delta_vs_prior_pct=delta,
        readings_per_day_avg=current.readings_per_day,
    )


def limits_of(profile: TargetProfile) -> RiskLimits:
    """The thresholds of the patient's profile, read from the database."""
    return RiskLimits(
        tir_min_pct=profile.tir_min_pct,
        tbr_l1_max_pct=profile.tbr_l1_max_pct,
        tbr_l2_max_pct=profile.tbr_l2_max_pct,
        tar_l1_max_pct=profile.tar_l1_max_pct,
        tar_l2_max_pct=profile.tar_l2_max_pct,
        cv_max_pct=profile.cv_max_pct,
        min_data_sufficiency_pct=profile.min_data_sufficiency_pct,
    )


@final
class GetPatientRiskUseCase:
    """The risk of an assigned patient, from the service or from the rules (P11)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned_gate: AssignedPatientGate,
        targets: TargetProfilePort,
        series: GlucoseSeriesPort,
        profiles: PatientAiProfilePort,
        risks: RiskAssessmentPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._assigned = assigned_gate
        self._targets = targets
        self._series = series
        self._profiles = profiles
        self._risks = risks
        self._clock = clock

    def execute(self, actor: Actor, patient_id: UUID, window_days: int) -> RiskResult:
        """The assessment; the proxy stores it and answers with the fallback if
        needed."""
        actor.require(READ_PERMISSION)
        clinic_id = actor.clinic_id
        if clinic_id is None:
            raise PermissionDeniedError
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._assigned.enter(
                actor, READ_PERMISSION, patient_id, DataResource.AI_OUTPUTS
            )
            found = self._targets.for_patient(patient_id)
            if found is None:
                raise InsumapError(ErrorCode.INTERNAL_ERROR)
            diabetes = self._profiles.diabetes_type(patient_id)
            if diabetes is None:
                raise ResourceNotFoundError
            zone = ZoneInfo(found.timezone)
            period = window_period(window_days, self._clock.now(), zone)
            prior = previous_period(period)
            current = metrics_for(
                period,
                list(self._series.points(patient_id, period.start, period.end)),
                found.profile,
            )
            before = metrics_for(
                prior,
                list(self._series.points(patient_id, prior.start, prior.end)),
                found.profile,
            )
            unit.commit()  # keeps the audit row of the read (P09)
        request = RiskRequest(
            patient_id=patient_id,
            clinic_id=clinic_id,
            target_profile_id=found.profile.id,
            window_days=window_days,
            diabetes_type=diabetes,
            features=features_of(current, before),
            limits=limits_of(found.profile),
            is_sufficient=current.is_sufficient,
            window_start=period.start,
            window_end=period.end,
        )
        return self._risks.assess(request)
