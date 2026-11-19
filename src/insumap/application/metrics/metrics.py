"""Glycemic metrics and AGP of a patient, own or assigned (M7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import final
from uuid import UUID
from zoneinfo import ZoneInfo

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWorkPort,
)
from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.agp import AgpBin, AgpResolution, compute_agp
from insumap.domain.metrics.glycemic_metrics import (
    GlycemicMetrics,
    GlycemicMetricsCalculator,
    Signal,
)
from insumap.domain.metrics.target_profile import PatientTargets, TargetProfile
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from insumap.domain.metrics.window import GlucosePoint, GlucoseWindow
from insumap.domain.metrics.window_iterator import GlucoseWindowIterator, WindowSpec
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

MIDNIGHT = time(0, 0)
HOURS_IN_24H_WINDOW = 24
ANY_POINT = 1
"""A window with at least one reading has data; sufficiency is judged apart."""


class MetricWindow(StrEnum):
    """The ``window`` of the metrics endpoints."""

    LAST_24_HOURS = "24h"
    LAST_7_DAYS = "7d"
    LAST_14_DAYS = "14d"
    LAST_30_DAYS = "30d"

    @property
    def days(self) -> int | None:
        """Whole local days of the window; ``None`` for the rolling 24 hours."""
        return None if self is MetricWindow.LAST_24_HOURS else int(self.value[:-1])


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class MetricsPeriod:
    """An instant range and the local days inside it."""

    start: datetime
    end: datetime
    zone: ZoneInfo
    days: int | None


def period_of(window: MetricWindow, now: datetime, zone: ZoneInfo) -> MetricsPeriod:
    """The period a window means, in the zone of the clinic.

    ``Nd`` is N whole local days ending at the start of today (the day in
    progress is partial and left out); ``24h`` is the rolling day up to ``now``.
    """
    local_now = now.astimezone(zone)
    if window.days is None:
        start = (now.astimezone(UTC) - timedelta(hours=HOURS_IN_24H_WINDOW)).astimezone(
            zone
        )
        return MetricsPeriod(start=start, end=local_now, zone=zone, days=None)
    today = local_now.date()
    return MetricsPeriod(
        start=datetime.combine(today - timedelta(days=window.days), MIDNIGHT, zone),
        end=datetime.combine(today, MIDNIGHT, zone),
        zone=zone,
        days=window.days,
    )


def previous_period(period: MetricsPeriod) -> MetricsPeriod:
    """The period of the same size right before ``period``."""
    if period.days is None:
        length = period.end.astimezone(UTC) - period.start.astimezone(UTC)
        return MetricsPeriod(
            start=(period.start.astimezone(UTC) - length).astimezone(period.zone),
            end=period.start,
            zone=period.zone,
            days=None,
        )
    first = period.start.date() - timedelta(days=period.days)
    return MetricsPeriod(
        start=datetime.combine(first, MIDNIGHT, period.zone),
        end=period.start,
        zone=period.zone,
        days=period.days,
    )


def metrics_for(
    period: MetricsPeriod, points: list[GlucosePoint], profile: TargetProfile
) -> GlycemicMetrics:
    """Cut the period (P14) and compute its metrics with the profile."""
    window = GlucoseWindowIterator.window(
        points, period.start, period.end, min_points=ANY_POINT
    )
    if period.days is None:
        days: list[GlucoseWindow] = [window]
    else:
        days = list(
            GlucoseWindowIterator(
                window.points,
                WindowSpec.daily(
                    zone=period.zone,
                    first_day=period.start.date(),
                    days=period.days,
                    min_points=ANY_POINT,
                ),
            )
        )
    return GlycemicMetricsCalculator(profile).compute(window, days)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class MetricsInput:
    """Metrics of the own patient (``patient_id`` ``None``) or of an assigned one."""

    actor: Actor
    window: MetricWindow = MetricWindow.LAST_14_DAYS
    compare_previous: bool = True
    patient_id: UUID | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class MetricsResult:
    window: MetricWindow
    period_from: datetime
    period_to: datetime
    timezone: str
    profile: TargetProfile
    strategy_code: str
    on_target: bool | None
    metrics: GlycemicMetrics
    previous: GlycemicMetrics | None
    tir_delta_pct: Decimal | None


@final
class _PatientScope:
    """Resolves who is read and under which permission, inside the transaction."""

    def __init__(
        self,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        own: PermissionCode,
        assigned: PermissionCode,
    ) -> None:
        self._own_gate = own_gate
        self._assigned_gate = assigned_gate
        self._own = own
        self._assigned = assigned

    def patient_id(self, actor: Actor, patient_id: UUID | None) -> UUID:
        if patient_id is None:
            return self._own_gate.enter(actor, self._own).patient_id
        return self._assigned_gate.enter(actor, self._assigned, patient_id)


def _targets(ports: TargetProfilePort, patient_id: UUID) -> PatientTargets:
    found = ports.for_patient(patient_id)
    if found is None:
        raise InsumapError(ErrorCode.INTERNAL_ERROR)  # no profile seeded: a setup error
    return found


@final
class ComputeGlycemicMetricsUseCase:
    """``GET /patients/{patient_id}/metrics`` and ``GET /patients/own/metrics``."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        targets: TargetProfilePort,
        series: GlucoseSeriesPort,
        strategies: GlycemicTargetStrategyRegistry,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._scope = _PatientScope(
            own_gate,
            assigned_gate,
            PermissionCode.METRICS_READ_OWN,
            PermissionCode.METRICS_READ_ASSIGNED,
        )
        self._targets = targets
        self._series = series
        self._strategies = strategies
        self._clock = clock

    def execute(self, input: MetricsInput) -> MetricsResult:
        """The metrics of the window, with the previous one if asked."""
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._compute(input)

    def _compute(self, input: MetricsInput) -> MetricsResult:
        patient_id = self._scope.patient_id(input.actor, input.patient_id)
        found = _targets(self._targets, patient_id)
        profile = found.profile
        zone = ZoneInfo(found.timezone)
        current = period_of(input.window, self._clock.now(), zone)
        before = previous_period(current) if input.compare_previous else None
        start = (before or current).start
        points = list(self._series.points(patient_id, start, current.end))
        metrics = metrics_for(current, points, profile)
        previous = None if before is None else metrics_for(before, points, profile)
        strategy = self._strategies.for_profile(profile)
        delta = (
            metrics.tir_pct - previous.tir_pct
            if previous is not None
            and metrics.tir_pct is not None
            and previous.tir_pct is not None
            else None
        )
        return MetricsResult(
            window=input.window,
            period_from=current.start,
            period_to=current.end,
            timezone=found.timezone,
            profile=profile,
            strategy_code=strategy.code,
            on_target=strategy.is_on_target(metrics, profile),
            metrics=metrics,
            previous=previous,
            tir_delta_pct=delta,
        )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AgpInput:
    actor: Actor
    days: int | None = None
    resolution: AgpResolution = AgpResolution.HOUR
    patient_id: UUID | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AgpResult:
    bins: tuple[AgpBin, ...]
    range_low_mg_dl: Decimal
    range_high_mg_dl: Decimal
    data_sufficiency_pct: Decimal
    is_sufficient: bool


@final
class GetAgpUseCase:
    """``GET /patients/{patient_id}/metrics/agp``: percentiles by time of day."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        targets: TargetProfilePort,
        series: GlucoseSeriesPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._scope = _PatientScope(
            own_gate,
            assigned_gate,
            PermissionCode.METRICS_READ_OWN,
            PermissionCode.METRICS_READ_ASSIGNED,
        )
        self._targets = targets
        self._series = series
        self._clock = clock

    def execute(self, input: AgpInput) -> AgpResult:
        """The AGP of the last whole local days; without enough data, no bins."""
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            patient_id = self._scope.patient_id(input.actor, input.patient_id)
            found = _targets(self._targets, patient_id)
            profile = found.profile
            zone = ZoneInfo(found.timezone)
            today = self._clock.now().astimezone(zone).date()
            days = input.days or profile.min_days
            period = MetricsPeriod(
                start=datetime.combine(today - timedelta(days=days), MIDNIGHT, zone),
                end=datetime.combine(today, MIDNIGHT, zone),
                zone=zone,
                days=days,
            )
            points = list(self._series.points(patient_id, period.start, period.end))
        metrics = metrics_for(period, points, profile)
        usable = metrics.signal is Signal.CGM and metrics.is_sufficient
        return AgpResult(
            bins=compute_agp(points, zone, input.resolution) if usable else (),
            range_low_mg_dl=profile.range_low_mg_dl,
            range_high_mg_dl=profile.range_high_mg_dl,
            data_sufficiency_pct=metrics.data_sufficiency_pct,
            is_sufficient=usable,
        )
