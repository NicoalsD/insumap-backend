"""P06 Adapter: FhirPatientAdapter turns a FHIR R4 Patient into an import candidate."""

from typing import Any

import pytest

from insumap.application.onboarding.integration import SourceRow, SourceRowError
from insumap.domain.onboarding.vocabulary import ImportIssue
from insumap.infrastructure.integration.fhir.adapter import FhirPatientAdapter


def patient(**changes: Any) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        "identifier": [
            {"system": "urn:insumap:demo:mrn", "value": "DEMO-000060"},
            {"type": {"coding": [{"code": "CC"}]}, "value": "SIM-3131313"},
        ],
        "name": [{"family": "Paciente", "given": ["Mario", "Andrés"]}],
        "birthDate": "1959-08-08",
        "gender": "male",
    }
    resource.update(changes)
    return resource


def row(resource: object) -> SourceRow:
    return SourceRow(row_number=1, resource_type="Patient", data=resource)


def test_a_patient_becomes_a_candidate() -> None:
    candidate = FhirPatientAdapter().to_candidate(row(patient()))

    assert candidate.mrn == "DEMO-000060"
    assert candidate.document_type == "CC"
    assert candidate.document_number == "SIM-3131313"
    assert candidate.full_name == "Mario Andrés Paciente"
    assert candidate.birth_date == "1959-08-08"
    assert candidate.sex == "male"


def test_a_patient_without_the_mrn_identifier_keeps_no_mrn() -> None:
    resource = patient(
        identifier=[{"type": {"coding": [{"code": "CC"}]}, "value": "SIM-1"}]
    )

    candidate = FhirPatientAdapter().to_candidate(row(resource))

    assert candidate.mrn is None
    assert candidate.document_number == "SIM-1"


def test_a_patient_without_a_name_has_no_full_name() -> None:
    candidate = FhirPatientAdapter().to_candidate(row(patient(name=[])))

    assert candidate.full_name is None


@pytest.mark.parametrize("resource", [{"resourceType": "Observation"}, None, "texto"])
def test_a_resource_that_is_not_a_patient_is_unsupported(resource: object) -> None:
    with pytest.raises(SourceRowError) as error:
        FhirPatientAdapter().to_candidate(row(resource))

    assert error.value.issue is ImportIssue.RESOURCE_UNSUPPORTED
