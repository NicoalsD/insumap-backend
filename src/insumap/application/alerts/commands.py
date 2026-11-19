"""Decisions about alerts and their rules (P13)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.alerts.ports import (
    AlertRepositoryPort,
    AlertRuleRepositoryPort,
)
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.domain.alerts.alert import (
    ActorType,
    Alert,
    AlertPriority,
    AlertRuleVersion,
    AlertTransition,
    AlertType,
    RuleStatus,
)
from insumap.domain.alerts.escalation import EscalationStep, parse_escalation
from insumap.domain.alerts.rules import parse_rule_definition
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

RULE_ENTITY = "ALERT_RULE"
ALERT_ENTITY = "ALERT"
RULE_FIELDS = ("name", "alert_type", "priority", "level", "condition", "escalation")
RULE_CODE_PREFIX = "RULE_"
"""The code of a rule family: the id of its first version, which never changes."""
ALERT_MACHINE = "alert_rule"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAlertRuleCommand(Command[AlertRuleVersion]):
    """The clinic administrator publishes a new rule, active from version 1."""

    audit_action: ClassVar[str] = "ALERT_RULE_CREATED"
    audit_entity_type: ClassVar[str] = RULE_ENTITY

    name: str
    alert_type: AlertType
    priority: AlertPriority
    level: int | None
    condition: Mapping[str, object]
    escalation: Sequence[Mapping[str, object]]

    @override
    def audit_subject(self, result: AlertRuleVersion) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.rule_id,
            changed_fields=RULE_FIELDS,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAlertRuleVersionCommand(Command[AlertRuleVersion]):
    """The administrator publishes a new version; the active one is retired."""

    audit_action: ClassVar[str] = "ALERT_RULE_VERSIONED"
    audit_entity_type: ClassVar[str] = RULE_ENTITY

    rule_id: UUID
    name: str
    alert_type: AlertType
    priority: AlertPriority
    level: int | None
    condition: Mapping[str, object]
    escalation: Sequence[Mapping[str, object]]
    change_reason: str

    @override
    def audit_subject(self, result: AlertRuleVersion) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.rule_id,
            reason=Reason.parse(self.change_reason).text,
            changed_fields=RULE_FIELDS,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AcknowledgeAlertCommand(Command[Alert]):
    """A doctor of the patient, or the patient, takes the alert over."""

    audit_action: ClassVar[str] = "ALERT_ACKNOWLEDGED"
    audit_entity_type: ClassVar[str] = ALERT_ENTITY

    alert_id: UUID
    note: str | None

    @override
    def audit_subject(self, result: Alert) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.alert_id,
            changed_fields=("status", "acknowledged_by", "acknowledged_at"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveAlertCommand(Command[Alert]):
    """A doctor of the patient closes an acknowledged alert, with a note."""

    audit_action: ClassVar[str] = "ALERT_RESOLVED"
    audit_entity_type: ClassVar[str] = ALERT_ENTITY

    alert_id: UUID
    note: str

    @override
    def audit_subject(self, result: Alert) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.alert_id,
            reason=Reason.parse(self.note).text,
            changed_fields=("status", "resolved_by", "resolved_at", "resolution_note"),
        )


def _owned_clinic(actor: Actor) -> UUID:
    if actor.clinic_id is None:
        raise PermissionDeniedError
    return actor.clinic_id


def _validated(
    condition: Mapping[str, object], escalation: Sequence[Mapping[str, object]]
) -> tuple[EscalationStep, ...]:
    """Refuse a malformed condition or escalation before anything is written."""
    parse_rule_definition(condition)
    return parse_escalation(escalation)


def _rule_code(rule_id: UUID) -> str:
    return f"{RULE_CODE_PREFIX}{rule_id.hex.upper()}"


@final
class CreateAlertRuleCommandHandler(
    CommandHandler[CreateAlertRuleCommand, AlertRuleVersion]
):
    """Adds version 1 of a new rule family, active at once: there is no draft step."""

    def __init__(
        self, *, rules: AlertRuleRepositoryPort, ids: IdGenerator, clock: Clock
    ) -> None:
        self._rules = rules
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateAlertRuleCommand) -> AlertRuleVersion:
        actor = command.actor
        actor.require(PermissionCode.ALERT_RULES_MANAGE)
        clinic_id = _owned_clinic(actor)
        steps = _validated(command.condition, command.escalation)
        rule_id = self._ids.new_id()
        rule = AlertRuleVersion(
            rule_id=rule_id,
            clinic_id=clinic_id,
            code=_rule_code(rule_id),
            name=command.name,
            alert_type=command.alert_type,
            level=command.level,
            priority=command.priority,
            condition=dict(command.condition),
            escalation=steps,
            version=1,
            status=RuleStatus.ACTIVE,
            change_reason=None,
            created_by=actor.user_id,
            created_at=self._clock.now(),
            activated_at=self._clock.now(),
        )
        self._rules.add(rule)
        return rule


@final
class CreateAlertRuleVersionCommandHandler(
    CommandHandler[CreateAlertRuleVersionCommand, AlertRuleVersion]
):
    """Retires the active version and adds the next one, in that order.

    The retire goes first: the database allows one active version per family.
    Seeds (clinic-less rules) are read-only for a clinic, so versioning one is a
    ``404``; the clinic writes its own rule for the same purpose.
    """

    def __init__(
        self, *, rules: AlertRuleRepositoryPort, ids: IdGenerator, clock: Clock
    ) -> None:
        self._rules = rules
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateAlertRuleVersionCommand) -> AlertRuleVersion:
        actor = command.actor
        actor.require(PermissionCode.ALERT_RULES_MANAGE)
        clinic_id = _owned_clinic(actor)
        current = self._rules.get(command.rule_id)
        if current is None or current.clinic_id != clinic_id:
            raise ResourceNotFoundError
        active = self._rules.active_clinic_version(clinic_id, current.code)
        if active is None:
            raise InvalidStateTransitionError(
                ALERT_MACHINE, current.status.value, "version"
            )
        steps = _validated(command.condition, command.escalation)
        reason = Reason.parse(command.change_reason).text
        latest = max(
            v.version for v in self._rules.versions_of(clinic_id, current.code)
        )
        version = AlertRuleVersion(
            rule_id=self._ids.new_id(),
            clinic_id=clinic_id,
            code=current.code,
            name=command.name,
            alert_type=command.alert_type,
            level=command.level,
            priority=command.priority,
            condition=dict(command.condition),
            escalation=steps,
            version=latest + 1,
            status=RuleStatus.ACTIVE,
            change_reason=reason,
            created_by=actor.user_id,
            created_at=self._clock.now(),
            activated_at=self._clock.now(),
        )
        self._rules.retire(active.rule_id)
        self._rules.add(version)
        return version


class _AlertLoader:
    """The alert of the path, or ``404`` when the session cannot see it."""

    def __init__(self, alerts: AlertRepositoryPort) -> None:
        self._alerts = alerts

    def load(self, alert_id: UUID) -> Alert:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise ResourceNotFoundError
        return alert


def _save(
    alerts: AlertRepositoryPort, transition: AlertTransition, expected: int
) -> Alert:
    """Write the alert under its lock version, then its history row."""
    if not alerts.save(transition.alert, expected_lock_version=expected):
        raise ConflictError("ALERT_CHANGED")
    alerts.add_history(transition.change)
    return transition.alert


@final
class AcknowledgeAlertCommandHandler(CommandHandler[AcknowledgeAlertCommand, Alert]):
    """A doctor of the patient, or the patient itself, acknowledges the alert.

    The branch follows the permission held, and the permission is checked before
    any lookup, so a caller without it gets ``403`` whether or not the alert exists.
    """

    def __init__(
        self,
        *,
        alerts: AlertRepositoryPort,
        own_gate: OwnPatientGate,
        assigned_gate: AssignedPatientGate,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._alerts = alerts
        self._own = own_gate
        self._assigned = assigned_gate
        self._load = _AlertLoader(alerts)
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: AcknowledgeAlertCommand) -> Alert:
        actor = command.actor
        alert = self._authorize(actor, command.alert_id)
        note = None if command.note is None else Reason.parse(command.note).text
        transition = alert.acknowledge(
            change_id=self._ids.new_id(),
            by=actor.user_id,
            actor_type=ActorType.USER,
            at=self._clock.now(),
            note=note,
        )
        return _save(self._alerts, transition, alert.lock_version)

    def _authorize(self, actor: Actor, alert_id: UUID) -> Alert:
        if PermissionCode.ALERTS_ACKNOWLEDGE in actor.permissions:
            alert = self._load.load(alert_id)
            self._assigned.enter(
                actor,
                PermissionCode.ALERTS_ACKNOWLEDGE,
                alert.patient_id,
                DataResource.ALERTS,
            )
            return alert
        if PermissionCode.ALERTS_ACKNOWLEDGE_OWN in actor.permissions:
            scope = self._own.enter(actor, PermissionCode.ALERTS_ACKNOWLEDGE_OWN)
            alert = self._load.load(alert_id)
            if alert.patient_id != scope.patient_id:
                raise ResourceNotFoundError
            return alert
        actor.require(PermissionCode.ALERTS_ACKNOWLEDGE)
        raise PermissionDeniedError


@final
class ResolveAlertCommandHandler(CommandHandler[ResolveAlertCommand, Alert]):
    """A doctor of the patient closes an acknowledged alert, with the reason."""

    def __init__(
        self,
        *,
        alerts: AlertRepositoryPort,
        assigned_gate: AssignedPatientGate,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._alerts = alerts
        self._assigned = assigned_gate
        self._load = _AlertLoader(alerts)
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: ResolveAlertCommand) -> Alert:
        actor = command.actor
        actor.require(PermissionCode.ALERTS_RESOLVE)
        alert = self._load.load(command.alert_id)
        self._assigned.enter(
            actor, PermissionCode.ALERTS_RESOLVE, alert.patient_id, DataResource.ALERTS
        )
        note = Reason.parse(command.note).text
        transition = alert.resolve(
            change_id=self._ids.new_id(),
            by=actor.user_id,
            at=self._clock.now(),
            note=note,
        )
        return _save(self._alerts, transition, alert.lock_version)
