"""Ports of the alerts module built over the session holder."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.alerts.ports import (
    AlertRepositoryPort,
    AlertRuleRepositoryPort,
    AlertSummaryPort,
    GlucoseHistoryPort,
)
from insumap.infrastructure.persistence.alert_repositories import (
    AlertRepository,
    AlertRuleRepository,
    AlertSummaryRepository,
    GlucoseHistoryRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertsAdapters:
    """Ports of the alerts slice, wired by ``Container``."""

    rules: AlertRuleRepositoryPort
    alerts: AlertRepositoryPort
    history: GlucoseHistoryPort
    summary: AlertSummaryPort


def build_alerts_adapters(*, current: CurrentSession) -> AlertsAdapters:
    """Production adapters: PostgreSQL under the RLS context of each transaction."""
    return AlertsAdapters(
        rules=AlertRuleRepository(current),
        alerts=AlertRepository(current),
        history=GlucoseHistoryRepository(current),
        summary=AlertSummaryRepository(current),
    )
