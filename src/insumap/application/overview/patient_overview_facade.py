"""``GET /patients/{patient_id}/overview`` and ``GET /patients/own/overview`` (P10).

The start page of a patient in one call: recent readings with their target,
the metrics of the window, the active plan, the open alerts and the active
reminders. Reading it never calls the AI (the forecast and the recommendations
are separate endpoints).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID
from zoneinfo import ZoneInfo

from insumap.application.access.ports import DataResource
from insumap.application.alerts.ports import AlertFilter, AlertRepositoryPort
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.dashboard.ports import OpenAlertCountPort
from insumap.application.metrics.metrics import MetricWindow, metrics_for, period_of
from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.monitoring.paging import PageQuery
from insumap.application.monitoring.ports import GlucoseReadingPort, ReadingFilters
from insumap.application.reminders.ports import ReminderRepositoryPort
from insumap.application.treatment.ports import TreatmentPlanRepositoryPort
from insumap.domain.alerts.alert import Alert
from insumap.domain.alerts.state import AlertStatus
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics
from insumap.domain.metrics.target_profile import TargetProfile
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from insumap.domain.monitoring.glucose import GlucoseReading
from insumap.domain.reminders.reminder import Reminder
from insumap.domain.treatment.plan import TreatmentPlan
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits
from insumap.shared.time import Clock

OPEN_STATUSES = (AlertStatus.OPEN, AlertStatus.ESCALATED)


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientOverview:
    """Everything the start page shows; glucose values in mg/dL."""

    patient_id: UUID
    window: MetricWindow
    period_from: datetime
    period_to: datetime
    timezone: str
    profile: TargetProfile
    strategy_code: str
    on_target: bool | None
    metrics: GlycemicMetrics
    recent_readings: tuple[GlucoseReading, ...]
    active_plan: TreatmentPlan | None
    open_alerts: tuple[Alert, ...]
    open_alerts_count: int
    reminders: tuple[Reminder, ...]
    simulated: bool


@final
class PatientOverviewFacade:
    """Composes the overview of one patient under the scope of the caller.

    A doctor's read is one gate entry (permission, P11 and the granted audit row,
    P09) and one commit; the patient's own read uses the consent gate (C3) and
    writes no audit row, like the other own reads. The ports are composed
    directly: the metrics use cases open their own transaction and must not be
    nested here.

    Pattern: P10 Facade
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned: AssignedPatientGate,
        own: OwnPatientGate,
        targets: TargetProfilePort,
        series: GlucoseSeriesPort,
        readings: GlucoseReadingPort,
        plans: TreatmentPlanRepositoryPort,
        alerts: AlertRepositoryPort,
        open_alerts: OpenAlertCountPort,
        reminders: ReminderRepositoryPort,
        strategies: GlycemicTargetStrategyRegistry,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._assigned = assigned
        self._own = own
        self._targets = targets
        self._series = series
        self._readings = readings
        self._plans = plans
        self._alerts = alerts
        self._open_alerts = open_alerts
        self._reminders = reminders
        self._strategies = strategies
        self._clock = clock

    def for_assigned(
        self, actor: Actor, patient_id: UUID, window: MetricWindow
    ) -> PatientOverview:
        """The overview of an assigned patient; ``404`` for anyone else."""
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            scoped = self._assigned.enter(
                actor,
                PermissionCode.PATIENTS_READ_ASSIGNED,
                patient_id,
                DataResource.GLUCOSE_READINGS,
            )
            overview = self._compose(actor, scoped, window)
            uow.commit()  # keeps the audit row of the read (P09)
        return overview

    def for_own(self, actor: Actor, window: MetricWindow) -> PatientOverview:
        """The overview of the patient of the token (C3 applies)."""
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            scope = self._own.enter(actor, PermissionCode.PATIENTS_READ_OWN)
            overview = self._compose(actor, scope.patient_id, window)
            uow.commit()
        return overview

    def _compose(
        self, actor: Actor, patient_id: UUID, window: MetricWindow
    ) -> PatientOverview:
        found = self._targets.for_patient(patient_id)
        if found is None:
            raise InsumapError(ErrorCode.INTERNAL_ERROR)  # no profile seeded
        profile = found.profile
        period = period_of(window, self._clock.now(), ZoneInfo(found.timezone))
        points = list(self._series.points(patient_id, period.start, period.end))
        metrics = metrics_for(period, points, profile)
        strategy = self._strategies.for_profile(profile)
        open_alerts = self._open_alert_list(patient_id)
        reminders = self._reminders.list_for_patient(
            patient_id, PageRequest(limit=FieldLimits.PAGE_SIZE_DEFAULT)
        )
        plan = self._plans.active_for(patient_id)
        recent = self._readings.list(
            patient_id,
            PageQuery(limit=FieldLimits.PAGE_SIZE_DEFAULT),
            ReadingFilters(),
        )
        return PatientOverview(
            patient_id=patient_id,
            window=window,
            period_from=period.start,
            period_to=period.end,
            timezone=found.timezone,
            profile=profile,
            strategy_code=strategy.code,
            on_target=strategy.is_on_target(metrics, profile),
            metrics=metrics,
            recent_readings=tuple(recent),
            active_plan=plan,
            open_alerts=open_alerts,
            open_alerts_count=self._open_alerts.open_counts([patient_id]).get(
                patient_id, 0
            ),
            reminders=tuple(r for r in reminders.items if r.is_active),
            simulated=actor.clinic_is_demo,
        )

    def _open_alert_list(self, patient_id: UUID) -> tuple[Alert, ...]:
        found: list[Alert] = []
        for status in OPEN_STATUSES:
            page = self._alerts.list(
                AlertFilter(status=status, patient_id=patient_id),
                PageRequest(limit=FieldLimits.PAGE_SIZE_DEFAULT),
            )
            found.extend(page.items)
        return tuple(sorted(found, key=lambda alert: alert.opened_at, reverse=True))
