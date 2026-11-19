"""Rendering adapter of the report port: picks a family, then a creator (P02, P03)."""

from __future__ import annotations

from typing import Final, final, override

from insumap.application.reports.model import (
    ClinicReportData,
    PatientReportData,
    RenderedReport,
    ReportFormat,
    ReportRenderingPort,
)
from insumap.infrastructure.reports.creators import (
    ClinicReportCreator,
    PatientReportCreator,
)
from insumap.infrastructure.reports.documents import (
    HtmlReportDocumentFactory,
    PdfReportDocumentFactory,
    ReportDocumentFactory,
)
from insumap.shared.i18n.message_catalog import MessageCatalog


@final
class ReportRenderingAdapter(ReportRenderingPort):
    """Implements ``ReportRenderingPort`` over the creators and the families."""

    def __init__(self, messages: MessageCatalog) -> None:
        self._families: Final[dict[ReportFormat, ReportDocumentFactory]] = {
            ReportFormat.PDF: PdfReportDocumentFactory(),
            ReportFormat.HTML: HtmlReportDocumentFactory(),
        }
        self._patient = PatientReportCreator(messages)
        self._clinic = ClinicReportCreator(messages)

    @override
    def render_patient(
        self, data: PatientReportData, output: ReportFormat
    ) -> RenderedReport:
        generator = self._patient.generator_for(self._families[output])
        return generator.generate(data)

    @override
    def render_clinic(
        self, data: ClinicReportData, output: ReportFormat
    ) -> RenderedReport:
        generator = self._clinic.generator_for(self._families[output])
        return generator.generate(data)
