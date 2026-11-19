"""Use cases of the reports: check, read through the existing use cases, render (M10).

Every use case checks its permission and the rate limit first, writes the
``EXPORT`` row of ``audit.data_access_log`` in a committed transaction, and then
reads the data through the use cases of metrics, records, treatment and
administration. Those use cases audit their own reads (P09), so no clinical
value reaches a report without a row. Rendering happens last and outside any
transaction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessAction,
    DataAccessLogPort,
    DataAccessOutcome,
    DataAccessRecord,
    DataResource,
)
from insumap.application.alerts.queries import GetAlertSummaryUseCase
from insumap.application.clinics.ports import ClinicRepositoryPort
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWorkPort,
)
from insumap.application.metrics.metrics import (
    AgpInput,
    ComputeGlycemicMetricsUseCase,
    GetAgpUseCase,
    MetricsInput,
    MetricWindow,
)
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.monitoring.queries import (
    GetTimelineUseCase,
    ListRequest,
    TimelineInput,
)
from insumap.application.patients.ports import PatientRosterFilter
from insumap.application.patients.queries import ListPatientsInput, ListPatientsUseCase
from insumap.application.reports.model import (
    ClinicCount,
    ClinicReportData,
    PatientReportData,
    RenderedReport,
    ReportFormat,
    ReportHeader,
    ReportRenderingPort,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.application.treatment.queries import (
    GetOwnTreatmentPlanUseCase,
    ListTreatmentPlansUseCase,
)
from insumap.domain.clinic.clinic import Clinic
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.reports.disclosure import is_too_small, percentage
from insumap.domain.treatment.plan import PlanStatus, TreatmentPlan
from insumap.shared.field_limits import FieldLimits
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock

ACCOUNT_STATUS_ORDER: tuple[AccountStatus, ...] = (
    AccountStatus.IMPORTED,
    AccountStatus.INVITED,
    AccountStatus.ACTIVE,
    AccountStatus.SUSPENDED,
    AccountStatus.DEACTIVATED,
)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PatientReportInput:
    """A patient report: whose (``patient_id``), which window and which format."""

    actor: Actor
    window: MetricWindow
    output: ReportFormat
    patient_id: UUID | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicReportInput:
    actor: Actor
    output: ReportFormat


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PatientReadSources:
    """The existing use cases a patient report reads from."""

    metrics: ComputeGlycemicMetricsUseCase
    agp: GetAgpUseCase
    timeline: GetTimelineUseCase


PlanReader = Callable[[], TreatmentPlan | None]


def _export_record(
    *,
    actor: Actor,
    clinic_id: UUID,
    patient_id: UUID | None,
    purpose: AccessPurpose,
    clock: Clock,
) -> DataAccessRecord:
    return DataAccessRecord(
        occurred_at=clock.now(),
        clinic_id=clinic_id,
        actor_user_id=actor.user_id,
        actor_role=actor.role,
        patient_id=patient_id,
        resource=DataResource.REPORT,
        purpose=purpose,
        outcome=DataAccessOutcome.GRANTED,
        request_id=current_request_id(),
        action=DataAccessAction.EXPORT,
    )


def _header(
    *,
    clinic: Clinic,
    clock: Clock,
    patient_id: UUID | None = None,
    period: tuple[datetime, datetime] | None = None,
    window: str | None = None,
) -> ReportHeader:
    return ReportHeader(
        clinic_name=clinic.name,
        is_demo=clinic.is_demo,
        timezone=clinic.timezone,
        generated_at=clock.now(),
        period_from=None if period is None else period[0],
        period_to=None if period is None else period[1],
        window=window,
        patient_id=patient_id,
    )


def _gather_patient(
    *,
    actor: Actor,
    patient_id: UUID | None,
    window: MetricWindow,
    header_patient_id: UUID,
    sources: PatientReadSources,
    clinic: Clinic,
    clock: Clock,
    plan: PlanReader,
) -> PatientReportData:
    """Read the metrics, AGP, events and plan through their own use cases.

    ``patient_id`` selects the assigned patient for the doctor; ``None`` reads the
    patient of the token. The header always names the patient, so a report shared
    with the care team says whose it is.
    """
    metrics = sources.metrics.execute(
        MetricsInput(actor=actor, window=window, patient_id=patient_id)
    )
    agp = sources.agp.execute(
        AgpInput(actor=actor, days=window.days, patient_id=patient_id)
    )
    events = sources.timeline.execute(
        TimelineInput(
            actor=actor,
            patient_id=patient_id,
            request=ListRequest(
                start=metrics.period_from,
                end=metrics.period_to,
                limit=FieldLimits.REPORT_EVENTS_MAX,
            ),
        )
    )
    return PatientReportData(
        header=_header(
            clinic=clinic,
            clock=clock,
            patient_id=header_patient_id,
            period=(metrics.period_from, metrics.period_to),
            window=window.value,
        ),
        metrics=metrics.metrics,
        previous=metrics.previous,
        agp_bins=agp.bins,
        agp_sufficient=agp.is_sufficient,
        range_low_mg_dl=agp.range_low_mg_dl,
        range_high_mg_dl=agp.range_high_mg_dl,
        events=tuple(events.items),
        plan=plan(),
    )


@final
class GeneratePatientReportUseCase:
    """``POST /reports/patient``: a doctor's report of an assigned patient (RF-82)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: AssignedPatientGate,
        clinics: ClinicRepositoryPort,
        sources: PatientReadSources,
        plans: ListTreatmentPlansUseCase,
        rate_limit: RateLimitCheck,
        renderer: ReportRenderingPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._clinics = clinics
        self._sources = sources
        self._plans = plans
        self._rate_limit = rate_limit
        self._renderer = renderer
        self._clock = clock

    def execute(self, input: PatientReportInput) -> RenderedReport:
        actor = input.actor
        actor.require(PermissionCode.REPORTS_GENERATE_ASSIGNED)
        self._rate_limit.ensure(str(actor.user_id))
        if input.patient_id is None:
            raise ResourceNotFoundError
        patient_id = input.patient_id
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            self._gate.enter(
                actor,
                PermissionCode.REPORTS_GENERATE_ASSIGNED,
                patient_id,
                DataResource.REPORT,
                DataAccessAction.EXPORT,
            )
            clinic = _clinic_of(self._clinics, actor)
            uow.commit()  # keeps the EXPORT row of the report (P09)

        def doctor_plan() -> TreatmentPlan | None:
            page = self._plans.execute(
                actor,
                patient_id,
                PlanStatus.ACTIVE,
                PageRequest(limit=1),
            )
            return page.items[0] if page.items else None

        data = _gather_patient(
            actor=actor,
            patient_id=patient_id,
            header_patient_id=patient_id,
            window=input.window,
            sources=self._sources,
            clinic=clinic,
            clock=self._clock,
            plan=doctor_plan,
        )
        return self._renderer.render_patient(data, input.output)


@final
class GenerateOwnReportUseCase:
    """``POST /reports/own``: the patient's own report, for sharing (RF-82)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        clinics: ClinicRepositoryPort,
        log: DataAccessLogPort,
        sources: PatientReadSources,
        own_plan: GetOwnTreatmentPlanUseCase,
        rate_limit: RateLimitCheck,
        renderer: ReportRenderingPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._clinics = clinics
        self._log = log
        self._sources = sources
        self._own_plan = own_plan
        self._rate_limit = rate_limit
        self._renderer = renderer
        self._clock = clock

    def execute(self, input: PatientReportInput) -> RenderedReport:
        actor = input.actor
        actor.require(PermissionCode.REPORTS_GENERATE_OWN)
        self._rate_limit.ensure(str(actor.user_id))
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            scope = self._gate.enter(actor, PermissionCode.REPORTS_GENERATE_OWN)
            own_patient_id = scope.patient_id
            clinic = _clinic_of(self._clinics, actor)
            self._log.record_granted(
                _export_record(
                    actor=actor,
                    clinic_id=scope.clinic_id,
                    patient_id=own_patient_id,
                    purpose=AccessPurpose.SELF,
                    clock=self._clock,
                )
            )
            uow.commit()  # keeps the EXPORT row of the report (P09)

        def own_plan() -> TreatmentPlan | None:
            try:
                return self._own_plan.execute(actor)
            except ResourceNotFoundError:
                return None

        data = _gather_patient(
            actor=actor,
            patient_id=None,
            header_patient_id=own_patient_id,
            window=input.window,
            sources=self._sources,
            clinic=clinic,
            clock=self._clock,
            plan=own_plan,
        )
        return self._renderer.render_patient(data, input.output)


@final
class GenerateClinicReportUseCase:
    """``POST /reports/clinic``: counts for the administrator, never clinical values."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        clinics: ClinicRepositoryPort,
        log: DataAccessLogPort,
        patients: ListPatientsUseCase,
        alerts: GetAlertSummaryUseCase,
        rate_limit: RateLimitCheck,
        renderer: ReportRenderingPort,
        clock: Clock,
        small_count_threshold: int,
    ) -> None:
        self._uow = uow
        self._clinics = clinics
        self._log = log
        self._patients = patients
        self._alerts = alerts
        self._rate_limit = rate_limit
        self._renderer = renderer
        self._clock = clock
        self._threshold = small_count_threshold

    def execute(self, input: ClinicReportInput) -> RenderedReport:
        actor = input.actor
        actor.require(PermissionCode.REPORTS_GENERATE_CLINIC)
        self._rate_limit.ensure(str(actor.user_id))
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            clinic = _clinic_of(self._clinics, actor)
            self._log.record_granted(
                _export_record(
                    actor=actor,
                    clinic_id=clinic.clinic_id,
                    patient_id=None,
                    purpose=AccessPurpose.ADMINISTRATION,
                    clock=self._clock,
                )
            )
            uow.commit()  # keeps the EXPORT row of the report (P09)
        counts = self._patient_counts(actor)
        alerts = self._alerts.execute(actor)
        data = self._clinic_data(
            clinic, counts, alerts.open_count, alerts.escalated_count
        )
        return self._renderer.render_clinic(data, input.output)

    def _patient_counts(self, actor: Actor) -> dict[AccountStatus, int]:
        """Walk the roster page by page and count by account state (no names kept)."""
        counts = dict.fromkeys(ACCOUNT_STATUS_ORDER, 0)
        after: UUID | None = None
        while True:
            page = self._patients.execute(
                ListPatientsInput(
                    actor=actor,
                    filters=PatientRosterFilter(),
                    page=PageRequest(limit=FieldLimits.PAGE_SIZE_MAX, after=after),
                )
            )
            for row in page.items:
                counts[row.account_status] += 1
            if page.next_cursor is None or not page.items:
                return counts
            after = page.items[-1].patient_id

    def _clinic_data(
        self,
        clinic: Clinic,
        counts: dict[AccountStatus, int],
        open_alerts: int,
        escalated_alerts: int,
    ) -> ClinicReportData:
        threshold = self._threshold
        total = sum(counts.values())
        active = counts[AccountStatus.ACTIVE]
        return ClinicReportData(
            header=_header(clinic=clinic, clock=self._clock),
            threshold=threshold,
            total_patients=None if is_too_small(total, threshold) else total,
            by_status=tuple(
                ClinicCount(
                    status=status,
                    count=None
                    if is_too_small(counts[status], threshold)
                    else counts[status],
                )
                for status in ACCOUNT_STATUS_ORDER
            ),
            activation_pct=percentage(active, total, threshold),
            open_alerts=None if is_too_small(open_alerts, threshold) else open_alerts,
            escalated_alerts=None
            if is_too_small(escalated_alerts, threshold)
            else escalated_alerts,
        )


def _clinic_of(clinics: ClinicRepositoryPort, actor: Actor) -> Clinic:
    if actor.clinic_id is None:
        raise PermissionDeniedError
    clinic = clinics.get(actor.clinic_id)
    if clinic is None:
        raise ResourceNotFoundError
    return clinic
