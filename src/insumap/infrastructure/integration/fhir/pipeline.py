"""The FHIR import: the P20 pipeline with the FHIR family.

Pattern: P20 Template Method
"""

from __future__ import annotations

from typing import final, override

from insumap.application.onboarding.integration import ClinicIntegrationFactory
from insumap.application.onboarding.pipeline import PatientImportPipeline
from insumap.infrastructure.integration.fhir.family import FhirIntegrationFactory


@final
class FhirPatientImportPipeline(PatientImportPipeline):
    """Reads the bytes as they are; the Bundle parser checks their shape.

    Pattern: P20 Template Method
    """

    @override
    def read(self, content: bytes) -> bytes:
        return content

    @override
    def integration_factory(self) -> ClinicIntegrationFactory:
        return FhirIntegrationFactory()
