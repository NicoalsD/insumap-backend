"""P20 Template Method: the fixed order of a report and its mandatory parts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from insumap.application.reports.model import (
    ClinicReportData,
    PatientReportData,
    ReportFormat,
    ReportHeader,
)
from insumap.domain.metrics.glycemic_metrics import Confidence, GlycemicMetrics, Signal
from insumap.infrastructure.reports.creators import (
    ClinicReportCreator,
    PatientReportCreator,
)
from insumap.infrastructure.reports.documents import (
    HtmlReportDocumentFactory,
    ReportDocumentFactory,
    ReportText,
    ReportWriter,
)
from insumap.shared.i18n.message_catalog import MessageCatalog

CATALOG = MessageCatalog.load_spanish()
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
DISCLAIMER = CATALOG.render("report.disclaimer")
DEMO_MARK = CATALOG.render("demo.mark")


class RecordingWriter(ReportWriter):
    def __init__(self) -> None:
        self.steps: list[str] = []

    def title(self, text: str) -> None:
        self.steps.append(f"title:{text}")

    def heading(self, text: str) -> None:
        self.steps.append(f"heading:{text}")

    def paragraph(self, text: str) -> None:
        self.steps.append(f"paragraph:{text}")

    def note(self, text: str) -> None:
        self.steps.append(f"note:{text}")

    def table(self, headers: object, rows: object) -> None:
        self.steps.append("table")

    def render(self) -> bytes:
        return b""


class SpyDocuments(ReportDocumentFactory):
    """Counts the writers asked and records their steps."""

    def __init__(self) -> None:
        self.writers: list[RecordingWriter] = []

    @property
    def output(self) -> ReportFormat:
        return ReportFormat.HTML

    @property
    def media_type(self) -> str:
        return "text/plain"

    def create_text(self) -> ReportText:
        return HtmlReportDocumentFactory().create_text()

    def create_writer(self) -> ReportWriter:
        writer = RecordingWriter()
        self.writers.append(writer)
        return writer


def _header(*, is_demo: bool) -> ReportHeader:
    return ReportHeader(
        clinic_name="Clínica",
        is_demo=is_demo,
        timezone="America/Bogota",
        generated_at=NOW,
    )


def _clinic_data(*, is_demo: bool) -> ClinicReportData:
    return ClinicReportData(
        header=_header(is_demo=is_demo),
        threshold=5,
        total_patients=None,
        by_status=(),
        activation_pct=None,
        open_alerts=None,
        escalated_alerts=None,
    )


def test_the_generator_writes_header_then_sections_then_footer() -> None:
    documents = SpyDocuments()
    rendered = (
        ClinicReportCreator(CATALOG)
        .generator_for(documents)
        .generate(_clinic_data(is_demo=False))
    )

    [writer] = documents.writers
    kinds = [step.split(":", 1)[0] for step in writer.steps]
    title_at = kinds.index("title")
    first_section = kinds.index("heading")
    last_note = len(kinds) - 1 - kinds[::-1].index("note")
    assert title_at == 0
    assert title_at < first_section < last_note
    assert writer.steps[last_note] == f"note:{DISCLAIMER}"
    assert rendered.media_type == "text/plain"


def test_the_demo_mark_is_written_in_the_header_and_the_footer_of_a_demo_clinic() -> (
    None
):
    documents = SpyDocuments()
    ClinicReportCreator(CATALOG).generator_for(documents).generate(
        _clinic_data(is_demo=True)
    )

    [writer] = documents.writers
    assert writer.steps.count(f"note:{DEMO_MARK}") == 2


def test_a_real_clinic_has_no_demo_mark_but_always_the_disclaimer() -> None:
    documents = SpyDocuments()
    ClinicReportCreator(CATALOG).generator_for(documents).generate(
        _clinic_data(is_demo=False)
    )

    [writer] = documents.writers
    assert f"note:{DEMO_MARK}" not in writer.steps
    assert f"note:{DISCLAIMER}" in writer.steps


def test_a_patient_report_with_no_data_still_carries_the_disclaimer() -> None:
    metrics = GlycemicMetrics(
        signal=Signal.CGM,
        data_sufficiency_pct=Decimal("0.00"),
        is_sufficient=False,
        confidence=Confidence.LOW_CONFIDENCE,
    )
    data = PatientReportData(
        header=_header(is_demo=False),
        metrics=metrics,
        previous=None,
        agp_bins=(),
        agp_sufficient=False,
        range_low_mg_dl=Decimal("70"),
        range_high_mg_dl=Decimal("180"),
        events=(),
        plan=None,
    )
    html = (
        PatientReportCreator(CATALOG)
        .generator_for(HtmlReportDocumentFactory())
        .generate(data)
        .content.decode("utf-8")
    )

    assert CATALOG.render("report.no_agp") in html
    assert CATALOG.render("report.no_events") in html
    assert CATALOG.render("report.no_plan") in html
    assert DISCLAIMER in html
