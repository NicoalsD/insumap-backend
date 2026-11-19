"""Listings and reads of the alerts and their rules (the caller's scope applies)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.alerts.ports import (
    AlertFilter,
    AlertRepositoryPort,
    AlertRuleRepositoryPort,
    AlertSummary,
    AlertSummaryPort,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.domain.alerts.alert import (
    Alert,
    AlertRuleVersion,
    AlertStatusChange,
    AlertType,
)
from insumap.domain.alerts.state import AlertStatus
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.errors import ErrorCode, InsumapError

PATIENT_ID_FIELD = "query.patient_id"


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertView:
    """An alert with its status history, oldest change first."""

    alert: Alert
    history: Sequence[AlertStatusChange]


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleView:
    """A rule version with every version of its family."""

    rule: AlertRuleVersion
    versions: Sequence[AlertRuleVersion]


@final
class ListAlertRulesUseCase:
    """``GET /alert-rules``: the active rules the session can see."""

    def __init__(self, *, uow: UnitOfWorkPort, rules: AlertRuleRepositoryPort) -> None:
        self._uow = uow
        self._rules = rules

    def execute(
        self, actor: Actor, *, alert_type: AlertType | None, page: PageRequest
    ) -> Page[AlertRuleVersion]:
        """One page of active rules."""
        actor.require(PermissionCode.ALERT_RULES_READ)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            return self._rules.list_active(alert_type, page)


@final
class GetAlertRuleUseCase:
    """``GET /alert-rules/{rule_id}``: the rule and the history of its versions."""

    def __init__(self, *, uow: UnitOfWorkPort, rules: AlertRuleRepositoryPort) -> None:
        self._uow = uow
        self._rules = rules

    def execute(self, actor: Actor, rule_id: UUID) -> AlertRuleView:
        """The rule, or ``404`` when the session cannot see it."""
        actor.require(PermissionCode.ALERT_RULES_READ)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            rule = self._rules.get(rule_id)
            if rule is None:
                raise ResourceNotFoundError
            versions = self._rules.versions_of(rule.clinic_id, rule.code)
        return AlertRuleView(rule=rule, versions=tuple(versions))


@final
class ListAlertsUseCase:
    """``GET /alerts``: a doctor sees assigned patients, a patient sees its own.

    Row level security lets a doctor see every alert of the clinic, so the
    assignment is applied here, and each patient of the page is audited through
    the access proxy (P11, P09) inside the same transaction.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        alerts: AlertRepositoryPort,
    ) -> None:
        self._uow = uow
        self._own = own_gate
        self._assigned = assigned_gate
        self._alerts = alerts

    def execute(
        self,
        actor: Actor,
        *,
        status: AlertStatus | None,
        alert_type: AlertType | None,
        opened_from: datetime | None,
        opened_to: datetime | None,
        patient_id: UUID | None,
        page: PageRequest,
    ) -> Page[Alert]:
        """One page of alerts, newest first."""
        filters = AlertFilter(
            status=status,
            alert_type=alert_type,
            opened_from=opened_from,
            opened_to=opened_to,
        )
        with self._uow.begin(TransactionContext.for_actor(actor)):
            if PermissionCode.ALERTS_READ_ASSIGNED in actor.permissions:
                if patient_id is not None:
                    self._assigned.enter(
                        actor,
                        PermissionCode.ALERTS_READ_ASSIGNED,
                        patient_id,
                        DataResource.ALERTS,
                    )
                    filters = replace(filters, patient_id=patient_id)
                else:
                    filters = replace(filters, assigned_to=actor.user_id)
                result = self._alerts.list(filters, page)
                if patient_id is None:
                    for patient in sorted(
                        {a.patient_id for a in result.items}, key=str
                    ):
                        self._assigned.enter(
                            actor,
                            PermissionCode.ALERTS_READ_ASSIGNED,
                            patient,
                            DataResource.ALERTS,
                        )
                return result
            scope = self._own.enter(actor, PermissionCode.ALERTS_READ_OWN)
            if patient_id is not None:
                raise InsumapError(
                    ErrorCode.VALIDATION_ERROR,
                    detail={
                        "errors": [{"field": PATIENT_ID_FIELD, "type": "not_allowed"}]
                    },
                )
            return self._alerts.list(
                replace(filters, patient_id=scope.patient_id), page
            )


@final
class GetAlertUseCase:
    """``GET /alerts/{alert_id}``: the alert with its history, for a caller in scope."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        alerts: AlertRepositoryPort,
    ) -> None:
        self._uow = uow
        self._own = own_gate
        self._assigned = assigned_gate
        self._alerts = alerts

    def execute(self, actor: Actor, alert_id: UUID) -> AlertView:
        """The alert, or ``404`` when it is not in the caller's scope."""
        with self._uow.begin(TransactionContext.for_actor(actor)):
            if PermissionCode.ALERTS_READ_ASSIGNED in actor.permissions:
                alert = self._find(alert_id)
                self._assigned.enter(
                    actor,
                    PermissionCode.ALERTS_READ_ASSIGNED,
                    alert.patient_id,
                    DataResource.ALERTS,
                )
            else:
                scope = self._own.enter(actor, PermissionCode.ALERTS_READ_OWN)
                alert = self._find(alert_id)
                if alert.patient_id != scope.patient_id:
                    raise ResourceNotFoundError
            history = self._alerts.history(alert_id)
        return AlertView(alert=alert, history=tuple(history))

    def _find(self, alert_id: UUID) -> Alert:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise ResourceNotFoundError
        return alert


@final
class GetAlertSummaryUseCase:
    """``GET /alerts/summary``: counts for the administrator, never clinical values."""

    def __init__(self, *, uow: UnitOfWorkPort, summary: AlertSummaryPort) -> None:
        self._uow = uow
        self._summary = summary

    def execute(self, actor: Actor) -> AlertSummary:
        """The counts of the session clinic."""
        actor.require(PermissionCode.ALERTS_READ_SUMMARY)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            return self._summary.summary()
