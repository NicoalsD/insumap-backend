"""What a report shows, in which formats, and the port that renders it (M10).

The data is read by the existing metrics, records, treatment and administration
use cases; the report only arranges it. Nothing here touches a framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import final
from uuid import UUID

from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.metrics.agp import AgpBin
from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics
from insumap.domain.monitoring.timeline import TimelineItem
from insumap.domain.treatment.plan import TreatmentPlan


class ReportFormat(StrEnum):
    """The two families of output. The same data goes into both."""

    PDF = "PDF"
    HTML = "HTML"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ReportHeader:
    """Who the report is about, for which period and whether it is simulated."""

    clinic_name: str
    is_demo: bool
    timezone: str
    generated_at: datetime
    period_from: datetime | None = None
    period_to: datetime | None = None
    window: str | None = None
    patient_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportData:
    """Common part of every report: the header and nothing clinical."""

    header: ReportHeader


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PatientReportData(ReportData):
    """AGP, metrics, events and plan of one patient for the period."""

    metrics: GlycemicMetrics
    previous: GlycemicMetrics | None
    agp_bins: tuple[AgpBin, ...]
    agp_sufficient: bool
    range_low_mg_dl: Decimal
    range_high_mg_dl: Decimal
    events: tuple[TimelineItem, ...]
    plan: TreatmentPlan | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicCount:
    """Patients in one account state. ``count`` is ``None`` when it is too small."""

    status: AccountStatus
    count: int | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicReportData(ReportData):
    """Counts of the clinic: no names, no glucose, no doses (RF-83).

    ``activation_pct`` is ``None`` when the clinic is too small to publish a rate.
    Adherence has no data source yet, so it is not in this report.
    """

    threshold: int
    total_patients: int | None
    by_status: tuple[ClinicCount, ...]
    activation_pct: Decimal | None
    open_alerts: int | None
    escalated_alerts: int | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedReport:
    """The bytes of a document and the media type that names them."""

    content: bytes
    media_type: str


class ReportRenderingPort(ABC):
    """Turns report data into a document (P02 creators, P03 families, P20 steps)."""

    @abstractmethod
    def render_patient(
        self, data: PatientReportData, output: ReportFormat
    ) -> RenderedReport:
        """The patient report in the requested format."""

    @abstractmethod
    def render_clinic(
        self, data: ClinicReportData, output: ReportFormat
    ) -> RenderedReport:
        """The clinic indicators in the requested format."""
