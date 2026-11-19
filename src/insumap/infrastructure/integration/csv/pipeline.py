"""The CSV import: the P20 pipeline with the CSV family.

Pattern: P20 Template Method
"""

from __future__ import annotations

from typing import final, override

from insumap.application.onboarding.integration import ClinicIntegrationFactory
from insumap.application.onboarding.pipeline import PatientImportPipeline
from insumap.infrastructure.integration.csv.family import (
    CsvIntegrationFactory,
    decode_csv_text,
)


@final
class CsvPatientImportPipeline(PatientImportPipeline):
    """Checks the encoding before any row is read (UTF-8, no BOM).

    Pattern: P20 Template Method
    """

    @override
    def read(self, content: bytes) -> bytes:
        decode_csv_text(content)
        return content

    @override
    def integration_factory(self) -> ClinicIntegrationFactory:
        return CsvIntegrationFactory()
