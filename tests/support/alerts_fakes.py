"""In-memory doubles of the alerts ports, plus a world the API tests can seed."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import override
from uuid import UUID

from insumap.application.alerts.ports import (
    AlertFilter,
    AlertRepositoryPort,
    AlertRuleRepositoryPort,
    AlertSummary,
    AlertSummaryPort,
    GlucoseHistoryPort,
)
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.alerts.alert import (
    GLUCOSE_ALERT_TYPES,
    Alert,
    AlertRuleVersion,
    AlertStatusChange,
    AlertType,
    RuleStatus,
)
from insumap.domain.metrics.window import GlucosePoint
from insumap.infrastructure.alerts_adapters import AlertsAdapters


class FakeAlertRules(AlertRuleRepositoryPort):
    def __init__(self, *rules: AlertRuleVersion) -> None:
        self.rows: dict[UUID, AlertRuleVersion] = {r.rule_id: r for r in rules}

    @override
    def get(self, rule_id: UUID) -> AlertRuleVersion | None:
        return self.rows.get(rule_id)

    @override
    def list_active(
        self, alert_type: AlertType | None, page: PageRequest
    ) -> Page[AlertRuleVersion]:
        rows = sorted(
            (
                r
                for r in self.rows.values()
                if r.status is RuleStatus.ACTIVE
                and (alert_type is None or r.alert_type is alert_type)
            ),
            key=lambda r: r.rule_id,
            reverse=True,
        )
        rows = [r for r in rows if page.after is None or r.rule_id < page.after]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda r: r.rule_id
        )

    @override
    def active_for_evaluation(self, clinic_id: UUID) -> Sequence[AlertRuleVersion]:
        return [
            r
            for r in self.rows.values()
            if r.status is RuleStatus.ACTIVE
            and r.alert_type in GLUCOSE_ALERT_TYPES
            and (r.clinic_id is None or r.clinic_id == clinic_id)
        ]

    @override
    def active_clinic_version(
        self, clinic_id: UUID, code: str
    ) -> AlertRuleVersion | None:
        for r in self.rows.values():
            if (
                r.clinic_id == clinic_id
                and r.code == code
                and r.status is RuleStatus.ACTIVE
            ):
                return r
        return None

    @override
    def versions_of(
        self, clinic_id: UUID | None, code: str
    ) -> Sequence[AlertRuleVersion]:
        found = [
            r for r in self.rows.values() if r.clinic_id == clinic_id and r.code == code
        ]
        return sorted(found, key=lambda r: r.version)

    @override
    def add(self, rule: AlertRuleVersion) -> None:
        self.rows[rule.rule_id] = rule

    @override
    def retire(self, rule_id: UUID) -> None:
        current = self.rows[rule_id]
        self.rows[rule_id] = _replace_status(current, RuleStatus.RETIRED)


def _replace_status(rule: AlertRuleVersion, status: RuleStatus) -> AlertRuleVersion:
    return replace(rule, status=status)


@dataclass
class FakeAlerts(AlertRepositoryPort):
    """Alerts, their history and the (doctor, patient) pairs of the list filter."""

    rows: dict[UUID, Alert] = field(default_factory=dict)
    history_rows: list[AlertStatusChange] = field(default_factory=list)
    assignments: set[tuple[UUID, UUID]] = field(default_factory=set)

    @override
    def get(self, alert_id: UUID) -> Alert | None:
        return self.rows.get(alert_id)

    @override
    def list(self, filters: AlertFilter, page: PageRequest) -> Page[Alert]:
        rows = sorted(self.rows.values(), key=lambda a: a.alert_id, reverse=True)
        out = []
        for alert in rows:
            if page.after is not None and alert.alert_id >= page.after:
                continue
            if filters.status is not None and alert.status is not filters.status:
                continue
            if (
                filters.alert_type is not None
                and alert.alert_type is not filters.alert_type
            ):
                continue
            if (
                filters.patient_id is not None
                and alert.patient_id != filters.patient_id
            ):
                continue
            if (
                filters.assigned_to is not None
                and (
                    filters.assigned_to,
                    alert.patient_id,
                )
                not in self.assignments
            ):
                continue
            out.append(alert)
        return build_page(
            out[: page.limit + 1], limit=page.limit, key=lambda a: a.alert_id
        )

    @override
    def has_open_for_rule(self, patient_id: UUID, rule_id: UUID) -> bool:
        return any(
            a.patient_id == patient_id
            and a.rule_id == rule_id
            and a.status.value in {"OPEN", "ESCALATED"}
            for a in self.rows.values()
        )

    @override
    def add(self, alert: Alert) -> None:
        self.rows[alert.alert_id] = alert

    @override
    def save(self, alert: Alert, *, expected_lock_version: int) -> bool:
        current = self.rows.get(alert.alert_id)
        if current is None or current.lock_version != expected_lock_version:
            return False
        self.rows[alert.alert_id] = alert
        return True

    @override
    def history(self, alert_id: UUID) -> Sequence[AlertStatusChange]:
        return [h for h in self.history_rows if h.alert_id == alert_id]

    @override
    def add_history(self, change: AlertStatusChange) -> None:
        self.history_rows.append(change)


class FakeGlucoseHistory(GlucoseHistoryPort):
    def __init__(self) -> None:
        self.readings: dict[UUID, tuple[UUID, GlucosePoint]] = {}

    def record(self, patient_id: UUID, reading_id: UUID, point: GlucosePoint) -> None:
        self.readings[reading_id] = (patient_id, point)

    @override
    def trigger(self, patient_id: UUID, reading_id: UUID) -> GlucosePoint | None:
        found = self.readings.get(reading_id)
        if found is None or found[0] != patient_id:
            return None
        return found[1]

    @override
    def in_effect(
        self, patient_id: UUID, since: datetime, until: datetime
    ) -> Sequence[GlucosePoint]:
        points = sorted(
            (
                p
                for pid, p in self.readings.values()
                if pid == patient_id and p.at <= until
            ),
            key=lambda p: p.at,
        )
        before = [p for p in points if p.at <= since]
        inside = [p for p in points if since < p.at]
        return ([before[-1]] if before else []) + inside


class FakeAlertSummary(AlertSummaryPort):
    def __init__(self, summary: AlertSummary | None = None) -> None:
        self.value = summary or AlertSummary(
            open_count=0, escalated_count=0, by_care_team=()
        )

    @override
    def summary(self) -> AlertSummary:
        return self.value


@dataclass
class AlertsWorld:
    """The alerts ports of an API test, seeded by the test."""

    rules: FakeAlertRules = field(default_factory=FakeAlertRules)
    alerts: FakeAlerts = field(default_factory=FakeAlerts)
    history: FakeGlucoseHistory = field(default_factory=FakeGlucoseHistory)
    summary: FakeAlertSummary = field(default_factory=FakeAlertSummary)

    def adapters(self) -> AlertsAdapters:
        return AlertsAdapters(
            rules=self.rules,
            alerts=self.alerts,
            history=self.history,
            summary=self.summary,
        )
