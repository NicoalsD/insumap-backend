"""Template method of the reports: the fixed order of a document (P20).

Pattern: P20 Template Method

Every report writes the same skeleton: the header (title, clinic, period and
the "Datos simulados" mark when the clinic is the demo), the sections that
differ by report, and the footer with the academic disclaimer. ``generate`` is
final, so no subclass can drop the mark or the disclaimer or reorder the steps.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal
from typing import final, override
from zoneinfo import ZoneInfo

from insumap.application.reports.model import (
    ClinicReportData,
    PatientReportData,
    RenderedReport,
    ReportData,
    ReportHeader,
)
from insumap.domain.metrics.agp import AgpBin
from insumap.domain.metrics.glycemic_metrics import GlycemicMetrics
from insumap.domain.monitoring.timeline import TimelineItem
from insumap.domain.treatment.plan import TreatmentPlan
from insumap.infrastructure.reports.documents import (
    ReportDocumentFactory,
    ReportWriter,
)
from insumap.shared.i18n.message_catalog import MessageCatalog

NOT_AVAILABLE: str = "-"
"""Shown where the data does not allow a value (never an empty cell)."""
TIMESTAMP_FORMAT: str = "%Y-%m-%d %H:%M"
EVENT_LABEL_KEYS: dict[str, str] = {
    "GLUCOSE": "report.event.glucose",
    "INSULIN": "report.event.insulin",
    "MEAL": "report.event.meal",
    "ACTIVITY": "report.event.activity",
    "SYMPTOM": "report.event.symptom",
}


def _value(number: Decimal | int | None, suffix: str = "") -> str:
    return NOT_AVAILABLE if number is None else f"{number}{suffix}"


def _local(instant: datetime, zone: str) -> str:
    return instant.astimezone(ZoneInfo(zone)).strftime(TIMESTAMP_FORMAT)


class ReportGenerator[D: ReportData](ABC):
    """Template of a report: header, sections and footer, in that order.

    Pattern: P20 Template Method
    """

    def __init__(
        self, documents: ReportDocumentFactory, messages: MessageCatalog
    ) -> None:
        self._documents = documents
        self._messages = messages

    @final
    def generate(self, data: D) -> RenderedReport:
        """Write the whole document in the fixed order and return its bytes."""
        writer = self._documents.create_writer()
        self.write_header(writer, data.header)
        self.write_sections(writer, data)
        self.write_footer(writer, data.header)
        return RenderedReport(
            content=writer.render(), media_type=self._documents.media_type
        )

    @final
    def write_header(self, writer: ReportWriter, header: ReportHeader) -> None:
        writer.title(self.title())
        writer.paragraph(
            self._messages.render("report.label.clinic") + ": " + header.clinic_name
        )
        if header.patient_id is not None:
            writer.paragraph(
                self._messages.render("report.label.patient")
                + ": "
                + str(header.patient_id)
            )
        if (
            header.window is not None
            and header.period_from is not None
            and header.period_to is not None
        ):
            writer.paragraph(
                self._messages.render("report.label.window")
                + ": "
                + header.window
                + " - "
                + self._messages.render(
                    "report.period.range",
                    start=_local(header.period_from, header.timezone),
                    end=_local(header.period_to, header.timezone),
                )
            )
        writer.paragraph(
            self._messages.render("report.label.generated_at")
            + ": "
            + _local(header.generated_at, header.timezone)
        )
        if header.is_demo:
            writer.note(self._messages.render("demo.mark"))

    @final
    def write_footer(self, writer: ReportWriter, header: ReportHeader) -> None:
        writer.note(self._messages.render("report.disclaimer"))
        if header.is_demo:
            writer.note(self._messages.render("demo.mark"))

    @abstractmethod
    def title(self) -> str:
        """The title of this report kind."""

    @abstractmethod
    def write_sections(self, writer: ReportWriter, data: D) -> None:
        """The body of this report kind."""


class PatientReport(ReportGenerator[PatientReportData]):
    """The clinical report of one patient: metrics, AGP, events and plan (RF-82)."""

    @override
    def title(self) -> str:
        return self._messages.render("report.title.patient")

    @override
    def write_sections(self, writer: ReportWriter, data: PatientReportData) -> None:
        self._metrics(writer, data.metrics, data.previous)
        self._agp(writer, data)
        self._events(writer, data.events, data.header.timezone)
        self._plan(writer, data.plan)

    def _metrics(
        self,
        writer: ReportWriter,
        metrics: GlycemicMetrics,
        previous: GlycemicMetrics | None,
    ) -> None:
        writer.heading(self._messages.render("report.section.metrics"))
        if not metrics.is_sufficient:
            writer.paragraph(self._messages.render("report.insufficient"))
        rows = [
            (
                "report.metric.tir",
                _value(metrics.tir_pct),
                _value(None if previous is None else previous.tir_pct),
            ),
            (
                "report.metric.tbr",
                _value(metrics.tbr_pct),
                _value(None if previous is None else previous.tbr_pct),
            ),
            (
                "report.metric.tar",
                _value(metrics.tar_pct),
                _value(None if previous is None else previous.tar_pct),
            ),
            (
                "report.metric.mean",
                _value(metrics.mean_glucose_mg_dl),
                _value(None if previous is None else previous.mean_glucose_mg_dl),
            ),
            (
                "report.metric.gmi",
                _value(metrics.gmi_pct),
                _value(None if previous is None else previous.gmi_pct),
            ),
            (
                "report.metric.cv",
                _value(metrics.cv_pct),
                _value(None if previous is None else previous.cv_pct),
            ),
            (
                "report.metric.hypo",
                _value(metrics.hypo_events_count),
                _value(None if previous is None else previous.hypo_events_count),
            ),
            (
                "report.metric.sufficiency",
                _value(metrics.data_sufficiency_pct),
                NOT_AVAILABLE,
            ),
        ]
        writer.table(
            [
                self._messages.render("report.table.indicator"),
                self._messages.render("report.table.value"),
                self._messages.render("report.table.previous"),
            ],
            [
                (self._messages.render(key), current, prior)
                for key, current, prior in rows
            ],
        )

    def _agp(self, writer: ReportWriter, data: PatientReportData) -> None:
        writer.heading(self._messages.render("report.section.agp"))
        writer.paragraph(
            self._messages.render(
                "report.target_range",
                low=_value(data.range_low_mg_dl),
                high=_value(data.range_high_mg_dl),
            )
        )
        if not data.agp_sufficient or not data.agp_bins:
            writer.paragraph(self._messages.render("report.no_agp"))
            return
        writer.table(
            [
                self._messages.render("report.table.hour"),
                "p5",
                "p50",
                "p95",
            ],
            [_agp_row(bin_) for bin_ in data.agp_bins],
        )

    def _events(
        self, writer: ReportWriter, events: tuple[TimelineItem, ...], zone: str
    ) -> None:
        writer.heading(self._messages.render("report.section.events"))
        if not events:
            writer.paragraph(self._messages.render("report.no_events"))
            return
        writer.table(
            [
                self._messages.render("report.table.event"),
                self._messages.render("report.table.time"),
                self._messages.render("report.table.status"),
            ],
            [
                (
                    self._messages.render(EVENT_LABEL_KEYS[item.event_type.value]),
                    _local(item.occurred_at, zone),
                    item.status,
                )
                for item in events
            ],
        )

    def _plan(self, writer: ReportWriter, plan: TreatmentPlan | None) -> None:
        writer.heading(self._messages.render("report.section.plan"))
        if plan is None:
            writer.paragraph(self._messages.render("report.no_plan"))
            return
        writer.paragraph(
            self._messages.render(
                "report.plan.summary", version=plan.version, items=len(plan.items)
            )
        )


@final
class ClinicReport(ReportGenerator[ClinicReportData]):
    """Counts of the clinic for the administrator: no names, no clinical values."""

    @override
    def title(self) -> str:
        return self._messages.render("report.title.clinic")

    @override
    def write_sections(self, writer: ReportWriter, data: ClinicReportData) -> None:
        writer.heading(self._messages.render("report.section.clinic"))
        writer.table(
            [
                self._messages.render("report.table.indicator"),
                self._messages.render("report.table.value"),
            ],
            [
                (
                    self._messages.render("report.kpi.total"),
                    _count(self._messages, data.total_patients, data.threshold),
                ),
                (
                    self._messages.render("report.kpi.activation"),
                    _value(data.activation_pct),
                ),
                (
                    self._messages.render("report.kpi.open_alerts"),
                    _count(self._messages, data.open_alerts, data.threshold),
                ),
                (
                    self._messages.render("report.kpi.escalated_alerts"),
                    _count(self._messages, data.escalated_alerts, data.threshold),
                ),
            ],
        )
        writer.heading(self._messages.render("report.kpi.status_title"))
        writer.table(
            [
                self._messages.render("report.table.status"),
                self._messages.render("report.table.count"),
            ],
            [
                (
                    self._messages.render(
                        f"report.account.{item.status.value.lower()}"
                    ),
                    _count(self._messages, item.count, data.threshold),
                )
                for item in data.by_status
            ],
        )


def _agp_row(bin_: AgpBin) -> tuple[str, str, str, str]:
    hour, minute = divmod(bin_.minute_of_day, 60)
    return (f"{hour:02d}:{minute:02d}", str(bin_.p5), str(bin_.p50), str(bin_.p95))


def _count(messages: MessageCatalog, count: int | None, threshold: int) -> str:
    if count is None:
        return messages.render("report.small_count", threshold=threshold)
    return str(count)


@final
class PreVisitSummary(PatientReport):
    """The summary a doctor reads before a visit: the patient report, retitled.

    No endpoint of ``API.md`` 8.11 exposes it yet; the creator exists so the
    factory method covers the three report kinds of P02.
    """

    @override
    def title(self) -> str:
        return self._messages.render("report.title.pre_visit")
