"""The FHIR family of the patient import (P03): parser, mapper and validator.

Pattern: P03 Abstract Factory
"""

from __future__ import annotations

import json
from datetime import date
from typing import Final, final, override

from insumap.application.onboarding.integration import (
    ClinicIntegrationFactory,
    ImportValidator,
    ParsedSource,
    PatientRecordMapper,
    PatientSourceParser,
    SourceRow,
)
from insumap.domain.onboarding.patient import (
    PatientCandidate,
    ValidationResult,
    validate_patient,
)
from insumap.domain.onboarding.vocabulary import (
    DataOrigin,
    SourceFormat,
    stored_resource_type,
)
from insumap.infrastructure.integration.fhir.adapter import FhirPatientAdapter
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

BUNDLE_RESOURCE: Final = "Bundle"
ORIGIN_SYSTEM: Final = "https://insumap.example.test/fhir/CodeSystem/data-origin"
SIMULATED_CODE: Final = "SIMULATED"
MAX_JSON_DEPTH: Final = FieldLimits.FHIR_BUNDLE_MAX_DEPTH


@final
class FhirBundleParser(PatientSourceParser):
    """Reads a FHIR R4 Bundle (``collection`` or ``transaction``) of entries."""

    source_format: SourceFormat = SourceFormat.FHIR

    @override
    def parse(self, content: bytes) -> ParsedSource:
        try:
            bundle = json.loads(content)
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _invalid_body("not_json") from None
        if (
            not isinstance(bundle, dict)
            or bundle.get("resourceType") != BUNDLE_RESOURCE
        ):
            raise _invalid_body("not_bundle")
        if _depth(bundle) > MAX_JSON_DEPTH:
            raise _invalid_body("too_deep")
        entries = bundle.get("entry", [])
        if not isinstance(entries, list):
            raise _invalid_body("entry_not_list")
        if len(entries) > FieldLimits.FHIR_BUNDLE_MAX_ENTRIES:
            raise _invalid_body("too_many_entries")
        rows = tuple(
            SourceRow(
                row_number=number,
                resource_type=_resource_type(entry),
                data=entry.get("resource") if isinstance(entry, dict) else None,
            )
            for number, entry in enumerate(entries, start=1)
        )
        return ParsedSource(origin=_origin(bundle), rows=rows)


@final
class FhirImportValidator(ImportValidator):
    """The shared rules of the import, applied to a FHIR candidate."""

    source_format: SourceFormat = SourceFormat.FHIR

    @override
    def validate(self, candidate: PatientCandidate, *, today: date) -> ValidationResult:
        return validate_patient(candidate, today=today)


@final
class FhirIntegrationFactory(ClinicIntegrationFactory):
    """Builds the FHIR family of the import.

    Pattern: P03 Abstract Factory
    """

    @property
    @override
    def source_format(self) -> SourceFormat:
        return SourceFormat.FHIR

    @override
    def create_parser(self) -> PatientSourceParser:
        return FhirBundleParser()

    @override
    def create_mapper(self) -> PatientRecordMapper:
        return FhirPatientAdapter()

    @override
    def create_validator(self) -> ImportValidator:
        return FhirImportValidator()


def _invalid_body(kind: str) -> InsumapError:
    """A body that is not the Bundle the import expects: ``422``, no rows."""
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"field": "body", "type": kind}]},
    )


def _resource_type(entry: object) -> str | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("resource"), dict):
        return None
    raw = entry["resource"].get("resourceType")
    return stored_resource_type(raw) if isinstance(raw, str) else None


def _origin(bundle: dict[str, object]) -> DataOrigin:
    meta = bundle.get("meta")
    tags = meta.get("tag") if isinstance(meta, dict) else None
    if isinstance(tags, list):
        for tag in tags:
            if (
                isinstance(tag, dict)
                and tag.get("system") == ORIGIN_SYSTEM
                and tag.get("code") == SIMULATED_CODE
            ):
                return DataOrigin.SIMULATED
    return DataOrigin.REAL


def _depth(value: object, level: int = 1) -> int:
    if isinstance(value, dict):
        return max((_depth(item, level + 1) for item in value.values()), default=level)
    if isinstance(value, list):
        return max((_depth(item, level + 1) for item in value), default=level)
    return level
