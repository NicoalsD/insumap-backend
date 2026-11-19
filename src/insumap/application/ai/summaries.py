"""Pre-visit clinical summaries (IA5): create and read, for an assigned patient.

``POST`` builds the window of the patient inside the doctor's transaction, commits
it (audit row) and asks the proxy for the summary. ``GET`` reads a stored summary
and never calls the AI again (API.md 8.10).
"""

from __future__ import annotations

from typing import final
from uuid import UUID
from zoneinfo import ZoneInfo

from insumap.application.access.ports import DataResource
from insumap.application.ai.assessments import (
    ClinicalSummaryPort,
    SummaryRequest,
    SummaryResult,
)
from insumap.application.ai.records import (
    ClinicalSummaryReadPort,
    ClinicalSummaryView,
    PatientAiProfilePort,
)
from insumap.application.ai.risk import window_period
from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.metrics.metrics import metrics_for
from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock

GENERATE_PERMISSION = PermissionCode.CLINICAL_SUMMARIES_GENERATE


@final
class CreateClinicalSummaryUseCase:
    """``POST /patients/{patient_id}/clinical-summaries`` (IA5, rate limited per
    doctor)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned_gate: AssignedPatientGate,
        targets: TargetProfilePort,
        series: GlucoseSeriesPort,
        profiles: PatientAiProfilePort,
        summaries: ClinicalSummaryPort,
        rate_limit: RateLimitCheck,
        llm_real_data_allowed: bool,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._assigned = assigned_gate
        self._targets = targets
        self._series = series
        self._profiles = profiles
        self._summaries = summaries
        self._rate_limit = rate_limit
        self._llm_real_data_allowed = llm_real_data_allowed
        self._clock = clock

    def execute(
        self, actor: Actor, patient_id: UUID, period_days: int
    ) -> SummaryResult:
        """The stored summary. The LLM only sees simulated data unless configured."""
        actor.require(GENERATE_PERMISSION)
        clinic_id = actor.clinic_id
        if clinic_id is None:
            raise PermissionDeniedError
        self._rate_limit.ensure(str(actor.user_id))
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._assigned.enter(
                actor, GENERATE_PERMISSION, patient_id, DataResource.AI_OUTPUTS
            )
            found = self._targets.for_patient(patient_id)
            if found is None:
                raise InsumapError(ErrorCode.INTERNAL_ERROR)
            diabetes = self._profiles.diabetes_type(patient_id)
            if diabetes is None:
                raise ResourceNotFoundError
            zone = ZoneInfo(found.timezone)
            period = window_period(period_days, self._clock.now(), zone)
            current = metrics_for(
                period,
                list(self._series.points(patient_id, period.start, period.end)),
                found.profile,
            )
            unit.commit()  # keeps the audit row of the read (P09)
        request = SummaryRequest(
            patient_id=patient_id,
            clinic_id=clinic_id,
            target_profile_id=found.profile.id,
            requested_by=actor.user_id,
            period_start=period.start,
            period_end=period.end,
            diabetes_type=diabetes,
            metrics=current,
            target_tir_pct=found.profile.tir_min_pct,
            is_sufficient=current.is_sufficient,
            use_llm=actor.clinic_is_demo or self._llm_real_data_allowed,
            readings_per_day=current.readings_per_day,
        )
        return self._summaries.summarize(request)


@final
class GetClinicalSummaryUseCase:
    """``GET /patients/{patient_id}/clinical-summaries/{summary_id}``: a stored
    summary."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned_gate: AssignedPatientGate,
        summaries: ClinicalSummaryReadPort,
    ) -> None:
        self._uow = uow
        self._assigned = assigned_gate
        self._summaries = summaries

    def execute(
        self, actor: Actor, patient_id: UUID, summary_id: UUID
    ) -> ClinicalSummaryView:
        """The summary of that patient, or ``404`` (another patient reads the same)."""
        actor.require(GENERATE_PERMISSION)
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._assigned.enter(
                actor, GENERATE_PERMISSION, patient_id, DataResource.AI_OUTPUTS
            )
            view = self._summaries.get(summary_id)
            if view is None or view.patient_id != patient_id:
                raise ResourceNotFoundError
            unit.commit()  # keeps the audit row of the read (P09)
        return view
