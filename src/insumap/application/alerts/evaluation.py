"""Opening alerts when a glucose reading is saved (P17 subscriber, P08 rules).

The subscriber runs after the commit of the reading (P17). It works in its own
transaction as the system, inside the clinic of the event, and reads what it needs
from the database: the event carries identifiers only.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import final, override
from uuid import UUID

from insumap.application.alerts.ports import (
    AlertRepositoryPort,
    AlertRuleRepositoryPort,
    GlucoseHistoryPort,
)
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.events.publisher import EventSubscriber
from insumap.domain.alerts.alert import Alert, AlertRuleVersion
from insumap.domain.alerts.rules import AlertRuleNode, GlucoseEvidence
from insumap.domain.monitoring.events import GlucoseReadingRecorded
from insumap.shared.errors import InsumapError
from insumap.shared.time import Clock

logger = logging.getLogger(__name__)


def effective_rules(rules: Sequence[AlertRuleVersion]) -> tuple[AlertRuleVersion, ...]:
    """One rule per code: the clinic's own version wins over a seed of the same code."""
    chosen: dict[str, AlertRuleVersion] = {}
    for rule in rules:
        current = chosen.get(rule.code)
        if current is None or (
            current.clinic_id is None and rule.clinic_id is not None
        ):
            chosen[rule.code] = rule
    return tuple(chosen.values())


@final
class EvaluateAlertRulesOnReading(EventSubscriber[GlucoseReadingRecorded]):
    """Evaluates the clinic's active glucose rules and opens the alerts they raise.

    An alert is not opened again while the patient has an ``OPEN`` or ``ESCALATED``
    one of the same rule (the database keeps that unique too). A rule whose stored
    condition cannot be read is skipped and logged by its id only.

    Pattern: P17 Observer (subscriber of ``GlucoseReadingRecorded``)
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        rules: AlertRuleRepositoryPort,
        alerts: AlertRepositoryPort,
        history: GlucoseHistoryPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._rules = rules
        self._alerts = alerts
        self._history = history
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, event: GlucoseReadingRecorded) -> None:
        with self._uow.begin(TransactionContext.for_system(event.clinic_id)) as unit:
            trigger = self._history.trigger(event.patient_id, event.reading_id)
            if trigger is None:
                return
            evaluable = self._evaluable(event.clinic_id)
            if not evaluable:
                return
            span = max((node.lookback() for _, node in evaluable), default=timedelta(0))
            history = self._history.in_effect(
                event.patient_id, trigger.at - span, trigger.at
            )
            evidence = GlucoseEvidence(current=trigger, history=tuple(history))
            for rule, node in evaluable:
                if not node.matches(evidence):
                    continue
                if self._alerts.has_open_for_rule(event.patient_id, rule.rule_id):
                    continue
                transition = Alert.open(
                    alert_id=self._ids.new_id(),
                    change_id=self._ids.new_id(),
                    clinic_id=event.clinic_id,
                    patient_id=event.patient_id,
                    rule=rule,
                    trigger_reading_id=event.reading_id,
                    evidence={
                        "value_mg_dl": str(trigger.mg_dl),
                        "measured_at": trigger.at.isoformat(),
                    },
                    at=self._clock.now(),
                )
                self._alerts.add(transition.alert)
                self._alerts.add_history(transition.change)
            unit.commit()

    def _evaluable(
        self, clinic_id: UUID
    ) -> list[tuple[AlertRuleVersion, AlertRuleNode]]:
        """The effective glucose rules whose stored condition reads back."""
        found: list[tuple[AlertRuleVersion, AlertRuleNode]] = []
        for rule in effective_rules(self._rules.active_for_evaluation(clinic_id)):
            try:
                found.append((rule, rule.condition_node()))
            except InsumapError:
                logger.warning(
                    "Alert rule skipped: its condition is not readable",
                    extra={"rule_id": str(rule.rule_id)},
                )
        return found
