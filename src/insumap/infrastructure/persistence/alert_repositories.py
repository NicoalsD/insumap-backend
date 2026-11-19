"""``alerts.alert_rules``, ``alerts.alerts``, their history and the glucose inputs."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final, cast, final, override
from uuid import UUID

from sqlalchemy import exists, select, text, update
from sqlalchemy.engine import CursorResult

from insumap.application.alerts.ports import (
    AlertFilter,
    AlertRepositoryPort,
    AlertRuleRepositoryPort,
    AlertSummary,
    AlertSummaryPort,
    DoctorAlertCount,
    GlucoseHistoryPort,
)
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.alerts.alert import (
    GLUCOSE_ALERT_TYPES,
    ActorType,
    Alert,
    AlertPriority,
    AlertRuleVersion,
    AlertStatusChange,
    AlertType,
    RuleStatus,
)
from insumap.domain.alerts.escalation import parse_escalation
from insumap.domain.alerts.state import AlertStatus
from insumap.domain.metrics.window import GlucosePoint
from insumap.domain.monitoring.glucose import ReadingContext, ReadingSource
from insumap.infrastructure.persistence.monitoring_orm import GlucoseReadingOrm
from insumap.infrastructure.persistence.monitoring_repositories import is_current
from insumap.infrastructure.persistence.orm import (
    AlertOrm,
    AlertRuleOrm,
    AlertStatusHistoryOrm,
    CareAssignmentOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

ACTIVE: Final = "ACTIVE"
OPEN_STATUSES: Final = (AlertStatus.OPEN.value, AlertStatus.ESCALATED.value)
GLUCOSE_TYPES: Final = tuple(sorted(t.value for t in GLUCOSE_ALERT_TYPES))
SUMMARY_SQL: Final = text(
    "SELECT doctor_id, open_count, escalated_count, unattended_count"
    " FROM alerts.clinic_alert_summary()"
)
"""The clinic counts of ``alerts.clinic_alert_summary()`` (Modelo de datos 9.5).

The function is a SECURITY DEFINER in ``insumap-database``. A row with a null
``doctor_id`` carries the clinic totals; the others carry each doctor's count of
alerts nobody has acknowledged. Available since ``db-v0.4.0``.
"""


def _rule(row: AlertRuleOrm) -> AlertRuleVersion:
    return AlertRuleVersion(
        rule_id=row.id,
        clinic_id=row.clinic_id,
        code=row.code,
        name=row.name,
        alert_type=AlertType(row.alert_type),
        level=row.level,
        priority=AlertPriority(row.priority),
        condition=dict(row.definition),
        escalation=parse_escalation(row.escalation),
        version=row.version,
        status=RuleStatus(row.status),
        change_reason=row.change_reason,
        created_by=row.created_by,
        created_at=row.created_at,
        activated_at=row.activated_at,
    )


def _alert(row: AlertOrm) -> Alert:
    return Alert(
        alert_id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        rule_id=row.rule_id,
        alert_type=AlertType(row.alert_type),
        level=row.level,
        priority=AlertPriority(row.priority),
        status=AlertStatus(row.status),
        escalation_level=row.escalation_level,
        next_escalation_at=row.next_escalation_at,
        opened_at=row.opened_at,
        trigger_reading_id=row.trigger_reading_id,
        evidence=dict(row.evidence),
        is_fallback=row.is_fallback,
        acknowledged_by=row.acknowledged_by,
        acknowledged_at=row.acknowledged_at,
        resolved_by=row.resolved_by,
        resolved_at=row.resolved_at,
        resolution_note=row.resolution_note,
        updated_at=row.updated_at,
        lock_version=row.lock_version,
    )


def _change(row: AlertStatusHistoryOrm) -> AlertStatusChange:
    return AlertStatusChange(
        change_id=row.id,
        alert_id=row.alert_id,
        from_status=None if row.from_status is None else AlertStatus(row.from_status),
        to_status=AlertStatus(row.to_status),
        escalation_level=row.escalation_level,
        actor_user_id=row.actor_user_id,
        actor_type=ActorType(row.actor_type),
        note=row.note,
        occurred_at=row.occurred_at,
    )


@final
class AlertRuleRepository(AlertRuleRepositoryPort):
    """Rule versions under row level security: the clinic's and the seeds."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, rule_id: UUID) -> AlertRuleVersion | None:
        row = self._current.get().get(AlertRuleOrm, rule_id)
        return None if row is None else _rule(row)

    @override
    def list_active(
        self, alert_type: AlertType | None, page: PageRequest
    ) -> Page[AlertRuleVersion]:
        statement = (
            select(AlertRuleOrm)
            .where(AlertRuleOrm.status == ACTIVE)
            .order_by(AlertRuleOrm.id.desc())
        )
        if page.after is not None:
            statement = statement.where(AlertRuleOrm.id < page.after)
        if alert_type is not None:
            statement = statement.where(AlertRuleOrm.alert_type == alert_type.value)
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_rule(row) for row in rows],
            limit=page.limit,
            key=lambda rule: rule.rule_id,
        )

    @override
    def active_for_evaluation(self, clinic_id: UUID) -> Sequence[AlertRuleVersion]:
        rows = self._current.get().scalars(
            select(AlertRuleOrm).where(
                AlertRuleOrm.status == ACTIVE,
                AlertRuleOrm.alert_type.in_(GLUCOSE_TYPES),
                (AlertRuleOrm.clinic_id == clinic_id)
                | AlertRuleOrm.clinic_id.is_(None),
            )
        )
        return [_rule(row) for row in rows]

    @override
    def active_clinic_version(
        self, clinic_id: UUID, code: str
    ) -> AlertRuleVersion | None:
        row = (
            self._current.get()
            .scalars(
                select(AlertRuleOrm).where(
                    AlertRuleOrm.clinic_id == clinic_id,
                    AlertRuleOrm.code == code,
                    AlertRuleOrm.status == ACTIVE,
                )
            )
            .one_or_none()
        )
        return None if row is None else _rule(row)

    @override
    def versions_of(
        self, clinic_id: UUID | None, code: str
    ) -> Sequence[AlertRuleVersion]:
        rows = self._current.get().scalars(
            select(AlertRuleOrm)
            .where(
                AlertRuleOrm.clinic_id.is_not_distinct_from(clinic_id),
                AlertRuleOrm.code == code,
            )
            .order_by(AlertRuleOrm.version)
        )
        return [_rule(row) for row in rows]

    @override
    def add(self, rule: AlertRuleVersion) -> None:
        session = self._current.get()
        session.add(
            AlertRuleOrm(
                id=rule.rule_id,
                clinic_id=rule.clinic_id,
                code=rule.code,
                name=rule.name,
                alert_type=rule.alert_type.value,
                level=rule.level,
                priority=rule.priority.value,
                definition=dict(rule.condition),
                escalation=[step.to_definition() for step in rule.escalation],
                bypass_quiet_hours=False,
                patient_notice=None,
                version=rule.version,
                status=rule.status.value,
                change_reason=rule.change_reason,
                created_by=rule.created_by,
                activated_at=rule.activated_at,
                created_at=rule.created_at,
            )
        )
        session.flush()

    @override
    def retire(self, rule_id: UUID) -> None:
        self._current.get().execute(
            update(AlertRuleOrm)
            .where(AlertRuleOrm.id == rule_id)
            .values(status=RuleStatus.RETIRED.value)
        )


@final
class AlertRepository(AlertRepositoryPort):
    """Alerts and their history: the DOCTOR, PATIENT and SYSTEM policies apply."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, alert_id: UUID) -> Alert | None:
        row = self._current.get().get(AlertOrm, alert_id)
        return None if row is None else _alert(row)

    @override
    def list(self, filters: AlertFilter, page: PageRequest) -> Page[Alert]:
        statement = select(AlertOrm).order_by(AlertOrm.id.desc())
        if page.after is not None:
            statement = statement.where(AlertOrm.id < page.after)
        if filters.status is not None:
            statement = statement.where(AlertOrm.status == filters.status.value)
        if filters.alert_type is not None:
            statement = statement.where(AlertOrm.alert_type == filters.alert_type.value)
        if filters.opened_from is not None:
            statement = statement.where(AlertOrm.opened_at >= filters.opened_from)
        if filters.opened_to is not None:
            statement = statement.where(AlertOrm.opened_at <= filters.opened_to)
        if filters.patient_id is not None:
            statement = statement.where(AlertOrm.patient_id == filters.patient_id)
        if filters.assigned_to is not None:
            statement = statement.where(
                AlertOrm.patient_id.in_(
                    select(CareAssignmentOrm.patient_id).where(
                        CareAssignmentOrm.doctor_user_id == filters.assigned_to,
                        CareAssignmentOrm.ended_at.is_(None),
                    )
                )
            )
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_alert(row) for row in rows], limit=page.limit, key=lambda a: a.alert_id
        )

    @override
    def has_open_for_rule(self, patient_id: UUID, rule_id: UUID) -> bool:
        found = self._current.get().scalar(
            select(
                exists().where(
                    AlertOrm.patient_id == patient_id,
                    AlertOrm.rule_id == rule_id,
                    AlertOrm.status.in_(OPEN_STATUSES),
                )
            )
        )
        return bool(found)

    @override
    def add(self, alert: Alert) -> None:
        session = self._current.get()
        session.add(
            AlertOrm(
                id=alert.alert_id,
                clinic_id=alert.clinic_id,
                patient_id=alert.patient_id,
                rule_id=alert.rule_id,
                alert_type=alert.alert_type.value,
                level=alert.level,
                priority=alert.priority.value,
                status=alert.status.value,
                escalation_level=alert.escalation_level,
                next_escalation_at=alert.next_escalation_at,
                opened_at=alert.opened_at,
                trigger_reading_id=alert.trigger_reading_id,
                forecast_id=None,
                evidence=dict(alert.evidence),
                is_fallback=alert.is_fallback,
                acknowledged_by=alert.acknowledged_by,
                acknowledged_at=alert.acknowledged_at,
                resolved_by=alert.resolved_by,
                resolved_at=alert.resolved_at,
                resolution_note=alert.resolution_note,
                updated_at=alert.updated_at,
                lock_version=alert.lock_version,
            )
        )
        session.flush()

    @override
    def save(self, alert: Alert, *, expected_lock_version: int) -> bool:
        result = self._current.get().execute(
            update(AlertOrm)
            .where(
                AlertOrm.id == alert.alert_id,
                AlertOrm.lock_version == expected_lock_version,
            )
            .values(
                status=alert.status.value,
                escalation_level=alert.escalation_level,
                next_escalation_at=alert.next_escalation_at,
                acknowledged_by=alert.acknowledged_by,
                acknowledged_at=alert.acknowledged_at,
                resolved_by=alert.resolved_by,
                resolved_at=alert.resolved_at,
                resolution_note=alert.resolution_note,
                updated_at=alert.updated_at,
                lock_version=alert.lock_version,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    @override
    def history(self, alert_id: UUID) -> Sequence[AlertStatusChange]:
        rows = self._current.get().scalars(
            select(AlertStatusHistoryOrm)
            .where(AlertStatusHistoryOrm.alert_id == alert_id)
            .order_by(AlertStatusHistoryOrm.occurred_at, AlertStatusHistoryOrm.id)
        )
        return [_change(row) for row in rows]

    @override
    def add_history(self, change: AlertStatusChange) -> None:
        session = self._current.get()
        session.add(
            AlertStatusHistoryOrm(
                id=change.change_id,
                clinic_id=self._clinic_of(change.alert_id),
                alert_id=change.alert_id,
                from_status=None
                if change.from_status is None
                else change.from_status.value,
                to_status=change.to_status.value,
                escalation_level=change.escalation_level,
                actor_user_id=change.actor_user_id,
                actor_type=change.actor_type.value,
                note=change.note,
                occurred_at=change.occurred_at,
            )
        )
        session.flush()

    def _clinic_of(self, alert_id: UUID) -> UUID:
        clinic_id = self._current.get().scalar(
            select(AlertOrm.clinic_id).where(AlertOrm.id == alert_id)
        )
        if clinic_id is None:
            raise LookupError("alert of a history row is not visible")
        return clinic_id


def _point(row: GlucoseReadingOrm) -> GlucosePoint:
    return GlucosePoint(
        at=row.measured_at,
        mg_dl=row.value_mg_dl,
        source=ReadingSource(row.source),
        context=None if row.context is None else ReadingContext(row.context),
    )


@final
class GlucoseHistoryRepository(GlucoseHistoryPort):
    """Current readings only: an annulled or superseded row is not evidence."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def trigger(self, patient_id: UUID, reading_id: UUID) -> GlucosePoint | None:
        orm = GlucoseReadingOrm
        row = (
            self._current.get()
            .scalars(
                select(orm).where(
                    orm.id == reading_id,
                    orm.patient_id == patient_id,
                    is_current(orm),
                )
            )
            .one_or_none()
        )
        return None if row is None else _point(row)

    @override
    def in_effect(
        self, patient_id: UUID, since: datetime, until: datetime
    ) -> Sequence[GlucosePoint]:
        orm = GlucoseReadingOrm
        session = self._current.get()
        anchor = session.scalars(
            select(orm)
            .where(
                orm.patient_id == patient_id,
                orm.measured_at <= since,
                is_current(orm),
            )
            .order_by(orm.measured_at.desc())
            .limit(1)
        ).one_or_none()
        inside = session.scalars(
            select(orm)
            .where(
                orm.patient_id == patient_id,
                orm.measured_at > since,
                orm.measured_at <= until,
                is_current(orm),
            )
            .order_by(orm.measured_at)
        ).all()
        rows = ([] if anchor is None else [anchor]) + list(inside)
        return [_point(row) for row in rows]


@final
class AlertSummaryRepository(AlertSummaryPort):
    """Counts of the clinic through ``alerts.clinic_alert_summary()`` (definer)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def summary(self) -> AlertSummary:
        rows = self._current.get().execute(SUMMARY_SQL).all()
        totals = next((row for row in rows if row.doctor_id is None), None)
        return AlertSummary(
            open_count=0 if totals is None else int(totals.open_count),
            escalated_count=0 if totals is None else int(totals.escalated_count),
            by_care_team=tuple(
                DoctorAlertCount(
                    doctor_id=row.doctor_id, unattended_count=int(row.unattended_count)
                )
                for row in rows
                if row.doctor_id is not None
            ),
        )
