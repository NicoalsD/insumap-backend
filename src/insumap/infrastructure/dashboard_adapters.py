"""The adapters of the triage dashboard, the reviews, the notes and the KPIs."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.application.access.ports import DataAccessLogPort
from insumap.application.clinic_kpis.ports import ClinicKpiPort
from insumap.application.common.unit_of_work import TransactionFactory
from insumap.application.dashboard.ports import (
    ClinicalNotePort,
    OpenAlertCountPort,
    TriageReviewPort,
    TriageRosterPort,
)
from insumap.infrastructure.access.sql_data_access_log import SqlDataAccessLog
from insumap.infrastructure.persistence.dashboard_repositories import (
    ClinicalNoteRepository,
    ClinicKpiRepository,
    OpenAlertCountRepository,
    TriageReviewRepository,
    TriageRosterRepository,
)
from insumap.infrastructure.persistence.transactions import CurrentSession


@dataclass(frozen=True, slots=True, kw_only=True)
class DashboardAdapters:
    """Ports of the dashboard slice, wired by ``Container``."""

    roster: TriageRosterPort
    open_alerts: OpenAlertCountPort
    reviews: TriageReviewPort
    notes: ClinicalNotePort
    kpis: ClinicKpiPort
    audit: DataAccessLogPort


def build_dashboard_adapters(
    *, current: CurrentSession, transactions: TransactionFactory
) -> DashboardAdapters:
    """Production adapters over PostgreSQL; the audit writes like the records do."""
    return DashboardAdapters(
        roster=TriageRosterRepository(current),
        open_alerts=OpenAlertCountRepository(current),
        reviews=TriageReviewRepository(current),
        notes=ClinicalNoteRepository(current),
        kpis=ClinicKpiRepository(current),
        audit=SqlDataAccessLog(current, transactions),
    )
