"""The CSV family of the patient import (P03): parser, mapper and validator.

The file is UTF-8 without BOM, separated by ``,`` or ``;`` (read from the
header), with an optional first line ``# data_origin=SIMULATED; ...``.

Pattern: P03 Abstract Factory
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Final, final, override

from insumap.application.onboarding.integration import (
    ClinicIntegrationFactory,
    ImportValidator,
    ParsedSource,
    PatientRecordMapper,
    PatientSourceParser,
    SourceRow,
    SourceRowError,
)
from insumap.domain.onboarding.patient import (
    PatientCandidate,
    ValidationResult,
    validate_patient,
)
from insumap.domain.onboarding.vocabulary import (
    CSV_COLUMNS,
    CSV_REQUIRED_COLUMNS,
    DataOrigin,
    ImportIssue,
    SourceFormat,
)
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

BOM: Final = "﻿"
COMMENT_PREFIX: Final = "#"
SEPARATORS: Final = (",", ";")
ORIGIN_KEY: Final = "data_origin"
SIMULATED: Final = "SIMULATED"


@final
class CsvPatientParser(PatientSourceParser):
    """Reads the header, checks the columns and returns one source row per line."""

    source_format: SourceFormat = SourceFormat.CSV

    @override
    def parse(self, content: bytes) -> ParsedSource:
        text = decode_csv_text(content)
        origin, body = _split_comment(text)
        separator = _separator(body)
        reader = csv.reader(io.StringIO(body), delimiter=separator)
        try:
            header = [name.strip() for name in next(reader)]
        except StopIteration:
            raise _body_error("empty") from None
        _check_columns(header)
        rows = []
        for number, cells in enumerate(reader, start=1):
            if not any(cell.strip() for cell in cells):
                continue
            if number > FieldLimits.PATIENT_CSV_MAX_ROWS:
                raise _body_error("too_many_rows")
            data = (
                dict(zip(header, cells, strict=False))
                if len(cells) == len(header)
                else None
            )
            rows.append(SourceRow(row_number=number, resource_type=None, data=data))
        return ParsedSource(origin=origin, rows=tuple(rows))


@final
class CsvPatientRecordMapper(PatientRecordMapper):
    """Maps one CSV line (a column name to its cell) to the candidate fields.

    Pattern: P06 Adapter (the CSV counterpart of the FHIR adapter)
    """

    source_format: SourceFormat = SourceFormat.CSV

    @override
    def to_candidate(self, row: SourceRow) -> PatientCandidate:
        data = row.data
        if not isinstance(data, dict):
            raise SourceRowError(ImportIssue.SOURCE_ROW_INVALID)
        cells = {key: str(value) for key, value in data.items() if value is not None}
        if any(
            len(value) > FieldLimits.PATIENT_CSV_MAX_CELL_LENGTH
            for value in cells.values()
        ):
            raise SourceRowError(ImportIssue.CELL_TOO_LONG)
        return PatientCandidate(
            mrn=cells.get("mrn"),
            birth_date=cells.get("birth_date"),
            full_name=cells.get("full_name"),
            document_type=cells.get("document_type"),
            document_number=cells.get("document_number"),
            sex=cells.get("sex"),
            diabetes_type=cells.get("diabetes_type"),
            contact_email=cells.get("contact_email"),
            contact_phone=cells.get("contact_phone"),
        )


@final
class CsvImportValidator(ImportValidator):
    """The shared rules of the import, applied to a CSV candidate."""

    source_format: SourceFormat = SourceFormat.CSV

    @override
    def validate(self, candidate: PatientCandidate, *, today: date) -> ValidationResult:
        return validate_patient(candidate, today=today)


@final
class CsvIntegrationFactory(ClinicIntegrationFactory):
    """Builds the CSV family of the import.

    Pattern: P03 Abstract Factory
    """

    @property
    @override
    def source_format(self) -> SourceFormat:
        return SourceFormat.CSV

    @override
    def create_parser(self) -> PatientSourceParser:
        return CsvPatientParser()

    @override
    def create_mapper(self) -> PatientRecordMapper:
        return CsvPatientRecordMapper()

    @override
    def create_validator(self) -> ImportValidator:
        return CsvImportValidator()


def decode_csv_text(content: bytes) -> str:
    """The text of a CSV file: UTF-8 without BOM, or ``422`` before any row is read."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise _body_error("not_utf8") from None
    if text.startswith(BOM):
        raise _body_error("bom")
    return text


def _split_comment(text: str) -> tuple[DataOrigin, str]:
    """The declared origin from the optional first comment line, and the rest."""
    if not text.startswith(COMMENT_PREFIX):
        return DataOrigin.REAL, text
    first, _, rest = text.partition("\n")
    origin = DataOrigin.REAL
    for item in first.lstrip(COMMENT_PREFIX).split(";"):
        key, _, value = item.strip().partition("=")
        if key.strip() == ORIGIN_KEY and value.strip() == SIMULATED:
            origin = DataOrigin.SIMULATED
    return origin, rest


def _separator(body: str) -> str:
    header = body.split("\n", 1)[0]
    return ";" if header.count(";") > header.count(",") else ","


def _check_columns(header: list[str]) -> None:
    if len(header) > FieldLimits.PATIENT_CSV_MAX_COLUMNS:
        raise _body_error("too_many_columns")
    present = set(header)
    missing = [name for name in CSV_REQUIRED_COLUMNS if name not in present]
    if missing:
        raise InsumapError(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [
                    {"field": name, "type": "missing_column"} for name in missing
                ]
            },
        )
    unknown = [name for name in header if name not in CSV_COLUMNS]
    if unknown:
        raise InsumapError(
            ErrorCode.VALIDATION_ERROR,
            detail={
                "errors": [
                    {"field": name, "type": "unknown_column"} for name in unknown
                ]
            },
        )


def _body_error(kind: str) -> InsumapError:
    """A file that is not a readable patient CSV: ``422``, no rows."""
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"field": "body", "type": kind}]},
    )
