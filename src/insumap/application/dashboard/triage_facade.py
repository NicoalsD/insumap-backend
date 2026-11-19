"""``GET /dashboard/triage``: one call that composes the doctor's triage list (P10)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID
from zoneinfo import ZoneInfo

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessLogPort,
    DataAccessOutcome,
    DataAccessRecord,
    DataResource,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.dashboard.ports import (
    AssignedPatientRow,
    OpenAlertCountPort,
    TriageReviewPort,
    TriageRosterPort,
)
from insumap.application.metrics.metrics import MetricWindow, metrics_for, period_of
from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.domain.dashboard.triage import TriageAssessment, triage_flags
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from insumap.domain.metrics.window import GlucosePoint
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class TriageInput:
    """The doctor, the window, the optional review filter and the page asked for."""

    actor: Actor
    window: MetricWindow
    reviewed: bool | None
    page: PageRequest


@final
class DoctorDashboardFacade:
    """Triage of the assigned patients in one transaction.

    The list comes only from the doctor's open assignments (the access rule of
    P11 applied to the whole list). For every patient it reads the target profile,
    the glucose series of the window and the open alerts, judges the window with
    the glycemic strategy, sorts the list by risk and, for the page returned,
    writes one ``TRIAGE_LIST`` audit row per patient in a single batch insert
    (P09). The read is committed with that row, so a failed audit fails the read.

    Pattern: P10 Facade
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        roster: TriageRosterPort,
        targets: TargetProfilePort,
        series: GlucoseSeriesPort,
        open_alerts: OpenAlertCountPort,
        reviews: TriageReviewPort,
        audit: DataAccessLogPort,
        strategies: GlycemicTargetStrategyRegistry,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._roster = roster
        self._targets = targets
        self._series = series
        self._open_alerts = open_alerts
        self._reviews = reviews
        self._audit = audit
        self._strategies = strategies
        self._clock = clock

    def triage(self, input: TriageInput) -> Page[TriageAssessment]:
        """One page of the triage list, most urgent first."""
        actor = input.actor
        actor.require(PermissionCode.DASHBOARD_READ_ASSIGNED)
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            rows = self._roster.assigned_patients(actor.user_id)
            ids = [row.patient_id for row in rows]
            alerts = self._open_alerts.open_counts(ids)
            reviews = self._reviews.latest_reviews(actor.user_id, ids)
            assessments = sorted(
                (
                    self._assess(
                        input.window, row, alerts.get(row.patient_id, 0), reviews
                    )
                    for row in rows
                ),
                key=TriageAssessment.sort_key,
            )
            if input.reviewed is not None:
                assessments = [a for a in assessments if a.reviewed is input.reviewed]
            page = build_page(
                _after(assessments, input.page.after)[: input.page.limit + 1],
                limit=input.page.limit,
                key=lambda a: a.patient_id,
            )
            self._audit_listed(actor, page.items)
            uow.commit()  # keeps the audit rows of the list (P09)
        return page

    def _assess(
        self,
        window: MetricWindow,
        row: AssignedPatientRow,
        open_alerts: int,
        reviews: Mapping[UUID, datetime],
    ) -> TriageAssessment:
        found = self._targets.for_patient(row.patient_id)
        if found is None:
            raise InsumapError(ErrorCode.INTERNAL_ERROR)  # no profile seeded
        zone = ZoneInfo(found.timezone)
        period = period_of(window, self._clock.now(), zone)
        points: list[GlucosePoint] = list(
            self._series.points(row.patient_id, period.start, period.end)
        )
        metrics = metrics_for(period, points, found.profile)
        strategy = self._strategies.for_profile(found.profile)
        flags = triage_flags(
            has_readings=bool(points),
            is_sufficient=metrics.is_sufficient,
            on_target=strategy.is_on_target(metrics, found.profile),
            open_alerts=open_alerts,
        )
        last = points[-1] if points else None
        return TriageAssessment(
            patient_id=row.patient_id,
            full_name=row.full_name,
            flags=flags,
            open_alerts_count=open_alerts,
            tir_pct=metrics.tir_pct,
            last_reading_mg_dl=None if last is None else last.mg_dl,
            last_reading_at=None if last is None else last.at,
            reviewed_at=reviews.get(row.patient_id),
        )

    def _audit_listed(self, actor: Actor, listed: Sequence[TriageAssessment]) -> None:
        if not listed:
            return
        at = self._clock.now()
        request_id = current_request_id()
        self._audit.record_granted_many(
            [
                DataAccessRecord(
                    occurred_at=at,
                    clinic_id=actor.clinic_id,
                    actor_user_id=actor.user_id,
                    actor_role=actor.role,
                    patient_id=item.patient_id,
                    resource=DataResource.TRIAGE_LIST,
                    purpose=AccessPurpose.CARE,
                    outcome=DataAccessOutcome.GRANTED,
                    request_id=request_id,
                )
                for item in listed
            ]
        )


def _after(
    assessments: Sequence[TriageAssessment], after: UUID | None
) -> list[TriageAssessment]:
    """The rows behind the cursor; an unknown cursor starts from the top."""
    if after is None:
        return list(assessments)
    for index, item in enumerate(assessments):
        if item.patient_id == after:
            return list(assessments[index + 1 :])
    return list(assessments)
