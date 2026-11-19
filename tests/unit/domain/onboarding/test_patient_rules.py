"""Rules of the patient import: each field, its issues and the batch counters."""

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.onboarding.batch import ImportBatch, ImportTotals, RowOutcome
from insumap.domain.onboarding.patient import (
    PatientCandidate,
    normalize_document_number,
    validate_patient,
)
from insumap.domain.onboarding.vocabulary import (
    BatchStatus,
    DataOrigin,
    DiabetesType,
    DocumentType,
    ImportIssue,
    RowVerdict,
    Sex,
    SourceFormat,
)
from insumap.shared.field_limits import FieldLimits

TODAY = date(2026, 11, 19)
CLINIC = UUID(int=1)
ADMIN = UUID(int=2)
BATCH = UUID(int=3)
_NOW = datetime(2026, 11, 19, 12, tzinfo=UTC)


def valid_candidate(**changes: str | None) -> PatientCandidate:
    fields: dict[str, str | None] = {
        "mrn": "DEMO-000001",
        "birth_date": "1968-03-02",
        "full_name": "Pedro Paciente Demo",
        "document_type": "CC",
        "document_number": "SIM-1020304",
        "sex": "male",
        "diabetes_type": "t2d",
        "contact_email": "Pedro.Paciente@Example.Test",
        "contact_phone": "+57 300 000 0000",
    }
    fields.update(changes)
    return PatientCandidate(**fields)


def test_a_complete_row_becomes_a_normalized_patient() -> None:
    result = validate_patient(valid_candidate(), today=TODAY)

    assert result.errors == ()
    assert result.warnings == ()
    patient = result.patient
    assert patient is not None
    assert patient.mrn == "DEMO-000001"
    assert patient.birth_date == date(1968, 3, 2)
    assert patient.document_type is DocumentType.CC
    assert patient.document_number == "SIM-1020304"
    assert patient.document_last4 == "0304"
    assert patient.sex is Sex.MALE
    assert patient.diabetes_type is DiabetesType.T2D
    assert patient.contact_email == "pedro.paciente@example.test"


def test_optional_fields_default_without_warnings() -> None:
    result = validate_patient(
        valid_candidate(
            sex=None, diabetes_type=None, contact_email=None, contact_phone=None
        ),
        today=TODAY,
    )

    assert result.warnings == ()
    assert result.patient is not None
    assert result.patient.sex is Sex.UNKNOWN
    assert result.patient.diabetes_type is DiabetesType.OTHER
    assert result.patient.contact_email is None


@pytest.mark.parametrize(
    ("changes", "issue"),
    [
        ({"mrn": None}, ImportIssue.MRN_MISSING),
        ({"mrn": "   "}, ImportIssue.MRN_MISSING),
        ({"mrn": "BAD MRN"}, ImportIssue.MRN_INVALID),
        ({"mrn": "M" * (FieldLimits.MRN_MAX_LENGTH + 1)}, ImportIssue.MRN_INVALID),
        ({"birth_date": None}, ImportIssue.BIRTH_DATE_MISSING),
        ({"birth_date": "02/03/1968"}, ImportIssue.BIRTH_DATE_INVALID),
        ({"birth_date": "1968-02-30"}, ImportIssue.BIRTH_DATE_INVALID),
        ({"birth_date": "2026-11-20"}, ImportIssue.BIRTH_DATE_INVALID),
        ({"birth_date": "1800-01-01"}, ImportIssue.BIRTH_DATE_INVALID),
        ({"full_name": None}, ImportIssue.FULL_NAME_MISSING),
        (
            {"full_name": "N" * (FieldLimits.PATIENT_FULL_NAME_MAX_LENGTH + 1)},
            ImportIssue.FULL_NAME_TOO_LONG,
        ),
        ({"document_type": None}, ImportIssue.DOCUMENT_TYPE_MISSING),
        ({"document_type": "DNI"}, ImportIssue.DOCUMENT_TYPE_INVALID),
        ({"document_number": None}, ImportIssue.DOCUMENT_NUMBER_MISSING),
        ({"document_number": "12"}, ImportIssue.DOCUMENT_NUMBER_INVALID),
        ({"document_number": "ABC#$%"}, ImportIssue.DOCUMENT_NUMBER_INVALID),
        (
            {"document_number": "1" * (FieldLimits.DOCUMENT_NUMBER_MAX_LENGTH + 1)},
            ImportIssue.DOCUMENT_NUMBER_INVALID,
        ),
    ],
)
def test_each_required_field_reports_its_issue(
    changes: dict[str, str | None], issue: ImportIssue
) -> None:
    result = validate_patient(valid_candidate(**changes), today=TODAY)

    assert result.patient is None
    assert issue in result.errors


def test_every_issue_of_a_row_is_reported_together() -> None:
    result = validate_patient(PatientCandidate(), today=TODAY)

    assert result.errors == (
        ImportIssue.MRN_MISSING,
        ImportIssue.BIRTH_DATE_MISSING,
        ImportIssue.FULL_NAME_MISSING,
        ImportIssue.DOCUMENT_TYPE_MISSING,
        ImportIssue.DOCUMENT_NUMBER_MISSING,
    )


@pytest.mark.parametrize(
    ("changes", "warning"),
    [
        ({"sex": "unknownish"}, ImportIssue.SEX_UNKNOWN_VALUE),
        ({"diabetes_type": "T9"}, ImportIssue.DIABETES_TYPE_UNKNOWN_VALUE),
        ({"contact_email": "no-es-correo"}, ImportIssue.CONTACT_EMAIL_INVALID),
        (
            {"contact_phone": "1" * (FieldLimits.PATIENT_PHONE_MAX_LENGTH + 1)},
            ImportIssue.CONTACT_PHONE_INVALID,
        ),
    ],
)
def test_a_bad_optional_value_is_a_warning_and_keeps_the_row(
    changes: dict[str, str | None], warning: ImportIssue
) -> None:
    result = validate_patient(valid_candidate(**changes), today=TODAY)

    assert result.errors == ()
    assert result.warnings == (warning,)
    assert result.patient is not None


def test_document_normalization_drops_spaces_and_dots_only() -> None:
    assert normalize_document_number(" cc 1.020-304 ") == "CC1020-304"


def test_document_numbers_are_checked_after_normalization() -> None:
    result = validate_patient(valid_candidate(document_number=" 12.3 "), today=TODAY)

    assert ImportIssue.DOCUMENT_NUMBER_INVALID in result.errors


def test_issues_name_columns_not_values() -> None:
    assert ImportIssue.MRN_MISSING.column == "mrn"
    assert ImportIssue.DOCUMENT_NUMBER_INVALID.column == "document_number"
    assert ImportIssue.SOURCE_ROW_INVALID.column == "row"


def test_totals_count_each_verdict_once() -> None:
    outcomes = [
        RowOutcome(row_number=1, resource_type=None, verdict=RowVerdict.VALID),
        RowOutcome(row_number=2, resource_type=None, verdict=RowVerdict.WARNING),
        RowOutcome(row_number=3, resource_type=None, verdict=RowVerdict.ERROR),
        RowOutcome(row_number=4, resource_type=None, verdict=RowVerdict.DUPLICATE),
        RowOutcome(
            row_number=5, resource_type="Observation", verdict=RowVerdict.UNSUPPORTED
        ),
    ]

    totals = ImportTotals.from_outcomes(outcomes)

    assert totals == ImportTotals(total=5, valid=1, warning=1, error=1, skipped=1)


def make_batch(status: BatchStatus) -> ImportBatch:
    return ImportBatch(
        batch_id=BATCH,
        clinic_id=CLINIC,
        source_format=SourceFormat.CSV,
        data_origin=DataOrigin.REAL,
        status=status,
        file_sha256="0" * 64,
        file_size_bytes=10,
        totals=ImportTotals(),
        created_by=ADMIN,
        created_at=_NOW,
    )


def test_only_a_previewed_batch_can_be_confirmed() -> None:
    make_batch(BatchStatus.PREVIEWED).require_previewed("confirm")

    with pytest.raises(InvalidStateTransitionError):
        make_batch(BatchStatus.COMPLETED).require_previewed("confirm")


def test_completing_a_batch_sets_its_totals_and_finish_time() -> None:
    done = make_batch(BatchStatus.PREVIEWED).completed(
        totals=ImportTotals(total=2, valid=2, created=2), at=_NOW
    )

    assert done.status is BatchStatus.COMPLETED
    assert done.finished_at == _NOW
    assert done.totals.created == 2
    assert not done.simulated
