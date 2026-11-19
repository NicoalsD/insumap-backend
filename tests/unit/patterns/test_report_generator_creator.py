"""P02 Factory Method: each creator returns its own generator class."""

from __future__ import annotations

from typing import override

from insumap.application.reports.model import PatientReportData
from insumap.infrastructure.reports.creators import (
    ClinicReportCreator,
    PatientReportCreator,
    PreVisitSummaryCreator,
    ReportGeneratorCreator,
)
from insumap.infrastructure.reports.documents import (
    HtmlReportDocumentFactory,
    ReportDocumentFactory,
)
from insumap.infrastructure.reports.generators import (
    ClinicReport,
    PatientReport,
    PreVisitSummary,
    ReportGenerator,
)
from insumap.shared.i18n.message_catalog import MessageCatalog

CATALOG = MessageCatalog.load_spanish()


def test_each_creator_returns_its_own_generator_class() -> None:
    documents = HtmlReportDocumentFactory()

    assert isinstance(
        PatientReportCreator(CATALOG).generator_for(documents), PatientReport
    )
    assert isinstance(
        ClinicReportCreator(CATALOG).generator_for(documents), ClinicReport
    )
    assert isinstance(
        PreVisitSummaryCreator(CATALOG).generator_for(documents), PreVisitSummary
    )


def test_the_pre_visit_summary_is_a_patient_report_with_its_own_title() -> None:
    assert issubclass(PreVisitSummary, PatientReport)
    assert PreVisitSummary.title is not PatientReport.title


class CountingCreator(ReportGeneratorCreator[PatientReportData]):
    """Counts the calls of the factory method (the template calls it once)."""

    def __init__(self) -> None:
        super().__init__(CATALOG)
        self.calls: list[ReportDocumentFactory] = []

    @override
    def create_generator(
        self, documents: ReportDocumentFactory
    ) -> ReportGenerator[PatientReportData]:
        self.calls.append(documents)
        return PatientReport(documents, CATALOG)


def test_generator_for_delegates_to_the_factory_method_once() -> None:
    creator = CountingCreator()
    documents = HtmlReportDocumentFactory()

    creator.generator_for(documents)

    assert creator.calls == [documents]
