"""Factory method of the report generators (P02).

Pattern: P02 Factory Method

Each creator decides which generator class to build. The rendering adapter asks
a creator and never names a concrete generator, so a new report kind adds one
creator and leaves the adapter alone. The format is not decided here: the
document family (P03) is passed in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import final, override

from insumap.application.reports.model import (
    ClinicReportData,
    PatientReportData,
    ReportData,
)
from insumap.infrastructure.reports.documents import ReportDocumentFactory
from insumap.infrastructure.reports.generators import (
    ClinicReport,
    PatientReport,
    PreVisitSummary,
    ReportGenerator,
)
from insumap.shared.i18n.message_catalog import MessageCatalog


class ReportGeneratorCreator[D: ReportData](ABC):
    """Creator of the generators of one report kind.

    Pattern: P02 Factory Method
    """

    def __init__(self, messages: MessageCatalog) -> None:
        self._messages = messages

    @final
    def generator_for(self, documents: ReportDocumentFactory) -> ReportGenerator[D]:
        """The generator of this kind, writing with the given document family."""
        return self.create_generator(documents)

    @abstractmethod
    def create_generator(self, documents: ReportDocumentFactory) -> ReportGenerator[D]:
        """Factory method: each creator returns its own generator class."""


@final
class PatientReportCreator(ReportGeneratorCreator[PatientReportData]):
    @override
    def create_generator(
        self, documents: ReportDocumentFactory
    ) -> ReportGenerator[PatientReportData]:
        return PatientReport(documents, self._messages)


@final
class ClinicReportCreator(ReportGeneratorCreator[ClinicReportData]):
    @override
    def create_generator(
        self, documents: ReportDocumentFactory
    ) -> ReportGenerator[ClinicReportData]:
        return ClinicReport(documents, self._messages)


@final
class PreVisitSummaryCreator(ReportGeneratorCreator[PatientReportData]):
    @override
    def create_generator(
        self, documents: ReportDocumentFactory
    ) -> ReportGenerator[PatientReportData]:
        return PreVisitSummary(documents, self._messages)
