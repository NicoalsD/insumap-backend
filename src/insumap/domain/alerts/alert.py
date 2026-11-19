"""Rule versions and alerts: the rows of ``alerts.alert_rules`` and ``alerts.alerts``.

An alert keeps its rule version, so the history stays explainable after a new
version is published. Each change of status is an ``AlertStatusChange`` row, which
the repository appends and never updates.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, final
from uuid import UUID

from insumap.domain.alerts.escalation import EscalationStep
from insumap.domain.alerts.rules import AlertRuleNode, parse_rule_definition
from insumap.domain.alerts.state import AlertState, AlertStatus


class AlertType(StrEnum):
    """What an alert is about (``alerts.alerts.alert_type``)."""

    HYPOGLYCEMIA = "HYPOGLYCEMIA"
    HYPERGLYCEMIA = "HYPERGLYCEMIA"
    RATE_OF_CHANGE = "RATE_OF_CHANGE"
    ADHERENCE = "ADHERENCE"
    PREDICTIVE = "PREDICTIVE"
    SYMPTOM_ALARM = "SYMPTOM_ALARM"


GLUCOSE_ALERT_TYPES: Final = frozenset(
    {AlertType.HYPOGLYCEMIA, AlertType.HYPERGLYCEMIA, AlertType.RATE_OF_CHANGE}
)
"""The types the glucose evaluation on each reading produces."""


class AlertPriority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RuleStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ActorType(StrEnum):
    """Who made a change of status (``alert_status_history.actor_type``)."""

    USER = "USER"
    SYSTEM = "SYSTEM"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AlertRuleVersion:
    """One version of a rule. Versions of one ``code`` share the family, not the row."""

    rule_id: UUID
    clinic_id: UUID | None
    code: str
    name: str
    alert_type: AlertType
    level: int | None
    priority: AlertPriority
    condition: Mapping[str, object]
    escalation: tuple[EscalationStep, ...]
    version: int
    status: RuleStatus
    change_reason: str | None
    created_by: UUID | None
    created_at: datetime
    activated_at: datetime | None

    def condition_node(self) -> AlertRuleNode:
        """The composite of the stored condition (P08)."""
        return parse_rule_definition(self.condition)

    def is_for_glucose(self) -> bool:
        """Whether each glucose reading is evaluated against this rule."""
        return self.alert_type in GLUCOSE_ALERT_TYPES


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AlertStatusChange:
    """One row of ``alerts.alert_status_history``: append only."""

    change_id: UUID
    alert_id: UUID
    from_status: AlertStatus | None
    to_status: AlertStatus
    escalation_level: int
    actor_user_id: UUID | None
    actor_type: ActorType
    note: str | None
    occurred_at: datetime


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class AlertTransition:
    """The alert after a change, with the history row that records it."""

    alert: Alert
    change: AlertStatusChange


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Alert:
    """An alert of one patient, raised by one rule version."""

    alert_id: UUID
    clinic_id: UUID
    patient_id: UUID
    rule_id: UUID
    alert_type: AlertType
    level: int | None
    priority: AlertPriority
    status: AlertStatus
    escalation_level: int
    next_escalation_at: datetime | None
    opened_at: datetime
    trigger_reading_id: UUID | None
    evidence: Mapping[str, object]
    is_fallback: bool
    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    resolution_note: str | None
    updated_at: datetime
    lock_version: int

    @classmethod
    def open(
        cls,
        *,
        alert_id: UUID,
        change_id: UUID,
        clinic_id: UUID,
        patient_id: UUID,
        rule: AlertRuleVersion,
        trigger_reading_id: UUID | None,
        evidence: Mapping[str, object],
        at: datetime,
    ) -> AlertTransition:
        """Raise the alert: ``OPEN`` at level 0, first escalation due."""
        first_step = rule.escalation[0] if rule.escalation else None
        alert = cls(
            alert_id=alert_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            rule_id=rule.rule_id,
            alert_type=rule.alert_type,
            level=rule.level,
            priority=rule.priority,
            status=AlertStatus.OPEN,
            escalation_level=0,
            next_escalation_at=None if first_step is None else at + first_step.wait,
            opened_at=at,
            trigger_reading_id=trigger_reading_id,
            evidence=dict(evidence),
            is_fallback=False,
            acknowledged_by=None,
            acknowledged_at=None,
            resolved_by=None,
            resolved_at=None,
            resolution_note=None,
            updated_at=at,
            lock_version=0,
        )
        change = AlertStatusChange(
            change_id=change_id,
            alert_id=alert_id,
            from_status=None,
            to_status=AlertStatus.OPEN,
            escalation_level=0,
            actor_user_id=None,
            actor_type=ActorType.SYSTEM,
            note=None,
            occurred_at=at,
        )
        return AlertTransition(alert=alert, change=change)

    def acknowledge(
        self,
        *,
        change_id: UUID,
        by: UUID,
        actor_type: ActorType,
        at: datetime,
        note: str | None,
    ) -> AlertTransition:
        """Someone takes the alert over: the escalation stops."""
        target = AlertState.from_status(self.status).acknowledge().status
        alert = replace(
            self,
            status=target,
            next_escalation_at=None,
            acknowledged_by=by,
            acknowledged_at=at,
            updated_at=at,
            lock_version=self.lock_version + 1,
        )
        return AlertTransition(
            alert=alert,
            change=self._change(
                change_id=change_id,
                to=target,
                by=by,
                actor_type=actor_type,
                at=at,
                note=note,
            ),
        )

    def resolve(
        self, *, change_id: UUID, by: UUID, at: datetime, note: str
    ) -> AlertTransition:
        """Close an acknowledged alert, with the note that says how it ended."""
        target = AlertState.from_status(self.status).resolve().status
        alert = replace(
            self,
            status=target,
            next_escalation_at=None,
            resolved_by=by,
            resolved_at=at,
            resolution_note=note,
            updated_at=at,
            lock_version=self.lock_version + 1,
        )
        return AlertTransition(
            alert=alert,
            change=self._change(
                change_id=change_id,
                to=target,
                by=by,
                actor_type=ActorType.USER,
                at=at,
                note=note,
            ),
        )

    def _change(
        self,
        *,
        change_id: UUID,
        to: AlertStatus,
        by: UUID,
        actor_type: ActorType,
        at: datetime,
        note: str | None,
    ) -> AlertStatusChange:
        return AlertStatusChange(
            change_id=change_id,
            alert_id=self.alert_id,
            from_status=self.status,
            to_status=to,
            escalation_level=self.escalation_level,
            actor_user_id=by,
            actor_type=actor_type,
            note=note,
            occurred_at=at,
        )
