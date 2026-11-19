"""Ports of the alerts module. Infrastructure implements them over PostgreSQL."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.alerts.alert import (
    Alert,
    AlertRuleVersion,
    AlertStatusChange,
    AlertType,
)
from insumap.domain.alerts.state import AlertStatus
from insumap.domain.metrics.window import GlucosePoint


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertFilter:
    """The optional filters of ``GET /alerts``.

    ``assigned_to`` limits the alerts to the patients the doctor is assigned to
    (an open assignment); the row level security does not do it.
    """

    status: AlertStatus | None = None
    alert_type: AlertType | None = None
    opened_from: datetime | None = None
    opened_to: datetime | None = None
    patient_id: UUID | None = None
    assigned_to: UUID | None = None


class AlertRuleRepositoryPort(ABC):
    """``alerts.alert_rules`` as the session sees it (its clinic and the seeds)."""

    @abstractmethod
    def get(self, rule_id: UUID) -> AlertRuleVersion | None:
        """A rule version, or ``None`` if the session cannot see it."""

    @abstractmethod
    def list_active(
        self, alert_type: AlertType | None, page: PageRequest
    ) -> Page[AlertRuleVersion]:
        """The active rules visible to the session, newest first."""

    @abstractmethod
    def active_for_evaluation(self, clinic_id: UUID) -> Sequence[AlertRuleVersion]:
        """Every active glucose rule of the clinic and of the seeds."""

    @abstractmethod
    def active_clinic_version(
        self, clinic_id: UUID, code: str
    ) -> AlertRuleVersion | None:
        """The active version of a rule family owned by ``clinic_id``."""

    @abstractmethod
    def versions_of(
        self, clinic_id: UUID | None, code: str
    ) -> Sequence[AlertRuleVersion]:
        """Every version of a rule family of the clinic, oldest first."""

    @abstractmethod
    def add(self, rule: AlertRuleVersion) -> None:
        """Insert a new version row."""

    @abstractmethod
    def retire(self, rule_id: UUID) -> None:
        """Move an active version to ``RETIRED`` (the only change allowed on it)."""


class AlertRepositoryPort(ABC):
    """``alerts.alerts`` and its ``alert_status_history``."""

    @abstractmethod
    def get(self, alert_id: UUID) -> Alert | None:
        """An alert the session can see, or ``None``."""

    @abstractmethod
    def list(self, filters: AlertFilter, page: PageRequest) -> Page[Alert]:
        """A page of alerts, newest first."""

    @abstractmethod
    def has_open_for_rule(self, patient_id: UUID, rule_id: UUID) -> bool:
        """Whether the patient has an ``OPEN`` or ``ESCALATED`` alert of the rule."""

    @abstractmethod
    def add(self, alert: Alert) -> None:
        """Insert a new alert."""

    @abstractmethod
    def save(self, alert: Alert, *, expected_lock_version: int) -> bool:
        """Update the alert if its ``lock_version`` is still the expected one."""

    @abstractmethod
    def history(self, alert_id: UUID) -> Sequence[AlertStatusChange]:
        """The changes of an alert, oldest first."""

    @abstractmethod
    def add_history(self, change: AlertStatusChange) -> None:
        """Append one change; the table is append only."""


class GlucoseHistoryPort(ABC):
    """The current readings that the rules evaluate."""

    @abstractmethod
    def trigger(self, patient_id: UUID, reading_id: UUID) -> GlucosePoint | None:
        """The reading, if it is still current (not annulled nor superseded)."""

    @abstractmethod
    def in_effect(
        self, patient_id: UUID, since: datetime, until: datetime
    ) -> Sequence[GlucosePoint]:
        """The reading in effect at ``since``, then every one in ``(since, until]``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DoctorAlertCount:
    """Alerts nobody has acknowledged yet, for one doctor."""

    doctor_id: UUID
    unattended_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertSummary:
    """Counts only: never a glucose value nor a patient."""

    open_count: int
    escalated_count: int
    by_care_team: tuple[DoctorAlertCount, ...]


class AlertSummaryPort(ABC):
    """The clinic-wide counts of an administrator, read by a database function."""

    @abstractmethod
    def summary(self) -> AlertSummary:
        """The counts of the session clinic."""
