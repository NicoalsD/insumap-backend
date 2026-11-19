"""P03 Abstract Factory: the import families build coherent parts."""

from datetime import date
from pathlib import Path

import pytest

from insumap.application.onboarding.integration import SourceRowError
from insumap.domain.onboarding.patient import PatientCandidate
from insumap.domain.onboarding.vocabulary import DataOrigin, ImportIssue, SourceFormat
from insumap.infrastructure.integration.csv.family import CsvIntegrationFactory
from insumap.infrastructure.integration.fhir.family import FhirIntegrationFactory
from insumap.shared.errors import ErrorCode, InsumapError

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
TODAY = date(2026, 11, 19)


@pytest.mark.parametrize(
    "factory", [FhirIntegrationFactory(), CsvIntegrationFactory()], ids=["fhir", "csv"]
)
def test_every_product_of_a_family_reads_the_family_format(
    factory: FhirIntegrationFactory | CsvIntegrationFactory,
) -> None:
    assert factory.create_parser().source_format is factory.source_format
    assert factory.create_mapper().source_format is factory.source_format
    assert factory.create_validator().source_format is factory.source_format


def test_the_families_have_different_formats() -> None:
    assert FhirIntegrationFactory().source_format is SourceFormat.FHIR
    assert CsvIntegrationFactory().source_format is SourceFormat.CSV


def test_fhir_bundle_goes_through_the_three_fhir_parts() -> None:
    factory = FhirIntegrationFactory()
    content = (FIXTURES / "bundle_fhir_valido.json").read_bytes()

    parsed = factory.create_parser().parse(content)
    mapper, validator = factory.create_mapper(), factory.create_validator()
    results = []
    for row in parsed.rows:
        if row.resource_type != "Patient":
            continue
        candidate = mapper.to_candidate(row)
        results.append(validator.validate(candidate, today=TODAY))

    assert parsed.origin is DataOrigin.REAL
    assert [row.resource_type for row in parsed.rows] == [
        "Patient",
        "Patient",
        "Observation",
    ]
    assert [r.patient is not None for r in results] == [True, True]


def test_csv_file_goes_through_the_three_csv_parts() -> None:
    factory = CsvIntegrationFactory()
    content = (FIXTURES / "pacientes_validos.csv").read_bytes()

    parsed = factory.create_parser().parse(content)
    mapper, validator = factory.create_mapper(), factory.create_validator()
    results = [
        validator.validate(mapper.to_candidate(row), today=TODAY) for row in parsed.rows
    ]

    assert len(parsed.rows) == 3
    assert all(result.patient is not None for result in results)
    assert results[2].warnings == (
        ImportIssue.SEX_UNKNOWN_VALUE,
        ImportIssue.DIABETES_TYPE_UNKNOWN_VALUE,
        ImportIssue.CONTACT_EMAIL_INVALID,
    )


def test_a_simulated_origin_is_read_from_the_csv_comment_line() -> None:
    content = (
        b'# data_origin=SIMULATED; label="Datos simulados"; simulator_version=1\n'
        b"mrn,birth_date,full_name,document_type,document_number\n"
        b"DEMO-000050,1970-01-01,Paciente Simulado,CC,SIM-1111222\n"
    )

    parsed = CsvIntegrationFactory().create_parser().parse(content)

    assert parsed.origin is DataOrigin.SIMULATED
    assert len(parsed.rows) == 1


def test_semicolon_separated_csv_is_detected_from_the_header() -> None:
    content = (
        b"mrn;birth_date;full_name;document_type;document_number\n"
        b"DEMO-000051;1970-01-01;Paciente Punto Y Coma;CC;SIM-2222333\n"
    )

    parsed = CsvIntegrationFactory().create_parser().parse(content)
    candidate = CsvIntegrationFactory().create_mapper().to_candidate(parsed.rows[0])

    assert candidate.full_name == "Paciente Punto Y Coma"


@pytest.mark.parametrize(
    ("content", "kind"),
    [
        (b"\xff\xfe", "not_utf8"),
        ("﻿mrn,birth_date\n".encode(), "bom"),
        (b"", "empty"),
    ],
)
def test_an_unreadable_csv_file_is_a_422_before_any_row(
    content: bytes, kind: str
) -> None:
    with pytest.raises(InsumapError) as error:
        CsvIntegrationFactory().create_parser().parse(content)

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.detail == {"errors": [{"field": "body", "type": kind}]}


def test_a_csv_without_a_required_column_names_the_column() -> None:
    content = b"mrn,birth_date,full_name,document_type\nDEMO-1,1970-01-01,Nombre,CC\n"

    with pytest.raises(InsumapError) as error:
        CsvIntegrationFactory().create_parser().parse(content)

    assert error.value.detail == {
        "errors": [{"field": "document_number", "type": "missing_column"}]
    }


def test_a_csv_with_an_unknown_column_is_rejected() -> None:
    content = (
        b"mrn,birth_date,full_name,document_type,document_number,apodo\n"
        b"DEMO-1,1970-01-01,Nombre,CC,SIM-1,x\n"
    )

    with pytest.raises(InsumapError) as error:
        CsvIntegrationFactory().create_parser().parse(content)

    assert error.value.detail == {
        "errors": [{"field": "apodo", "type": "unknown_column"}]
    }


def test_a_row_with_the_wrong_cell_count_is_a_row_error_not_a_failure() -> None:
    content = (
        b"mrn,birth_date,full_name,document_type,document_number\n"
        b"DEMO-1,1970-01-01,Nombre\n"
    )
    parsed = CsvIntegrationFactory().create_parser().parse(content)

    with pytest.raises(SourceRowError) as error:
        CsvIntegrationFactory().create_mapper().to_candidate(parsed.rows[0])
    assert error.value.issue is ImportIssue.SOURCE_ROW_INVALID


def test_fhir_body_that_is_not_a_bundle_is_a_422() -> None:
    with pytest.raises(InsumapError) as error:
        FhirIntegrationFactory().create_parser().parse(b'{"resourceType": "Patient"}')

    assert error.value.detail == {"errors": [{"field": "body", "type": "not_bundle"}]}


def test_candidate_is_plain_data() -> None:
    candidate = PatientCandidate(mrn="DEMO-1")
    assert candidate.mrn == "DEMO-1"
