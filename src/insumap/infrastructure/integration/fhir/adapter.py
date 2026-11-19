"""FHIR R4 patient adapter (P06 Adapter): a ``Patient`` becomes a candidate.

Pattern: P06 Adapter
"""

from __future__ import annotations

from typing import final, override

from insumap.application.onboarding.integration import (
    PatientRecordMapper,
    SourceRow,
    SourceRowError,
)
from insumap.domain.onboarding.patient import PatientCandidate
from insumap.domain.onboarding.vocabulary import (
    DocumentType,
    ImportIssue,
    RowVerdict,
    SourceFormat,
)

PATIENT_RESOURCE: str = "Patient"
MRN_SYSTEM: str = "urn:insumap:demo:mrn"
DOCUMENT_CODES: frozenset[str] = frozenset(item.value for item in DocumentType)


@final
class FhirPatientAdapter(PatientRecordMapper):
    """Adapts a FHIR R4 ``Patient`` resource to the import candidate.

    The MRN is the identifier of the MRN system; a document is an identifier
    whose type code is a document type. Anything else is ignored.

    Pattern: P06 Adapter
    """

    source_format: SourceFormat = SourceFormat.FHIR

    @override
    def to_candidate(self, row: SourceRow) -> PatientCandidate:
        resource = row.data
        if (
            not isinstance(resource, dict)
            or resource.get("resourceType") != PATIENT_RESOURCE
        ):
            raise SourceRowError(
                ImportIssue.RESOURCE_UNSUPPORTED, RowVerdict.UNSUPPORTED
            )
        mrn, document_type, document_number = _identifiers(resource.get("identifier"))
        names = resource.get("name")
        first_name = names[0] if isinstance(names, list) and names else {}
        if not isinstance(first_name, dict):
            first_name = {}
        given = first_name.get("given")
        given_text = (
            " ".join(str(item) for item in given) if isinstance(given, list) else ""
        )
        family = first_name.get("family")
        full_name = " ".join(part for part in (given_text, str(family or "")) if part)
        birth = resource.get("birthDate")
        gender = resource.get("gender")
        return PatientCandidate(
            mrn=mrn,
            birth_date=birth if isinstance(birth, str) else None,
            full_name=full_name or None,
            document_type=document_type,
            document_number=document_number,
            sex=gender if isinstance(gender, str) else None,
        )


def _identifiers(raw: object) -> tuple[str | None, str | None, str | None]:
    """The MRN, the document type and the document number of a Patient."""
    mrn: str | None = None
    document_type: str | None = None
    document_number: str | None = None
    if not isinstance(raw, list):
        return mrn, document_type, document_number
    for identifier in raw:
        if not isinstance(identifier, dict):
            continue
        value = identifier.get("value")
        if not isinstance(value, str):
            continue
        code = _type_code(identifier.get("type"))
        if identifier.get("system") == MRN_SYSTEM:
            mrn = value
        elif code in DOCUMENT_CODES:
            document_type, document_number = code, value
    return mrn, document_type, document_number


def _type_code(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None
    coding = raw.get("coding")
    if not isinstance(coding, list) or not coding or not isinstance(coding[0], dict):
        return None
    code = coding[0].get("code")
    return code.upper() if isinstance(code, str) else None
