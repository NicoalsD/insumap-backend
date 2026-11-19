"""Vocabulary of a patient import: formats, statuses, document types and issues.

Issue codes never carry personal data: an error report names the column and
the rule that failed, never the value that failed.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final


class SourceFormat(StrEnum):
    """Format of an import file (``clinic.import_batches.source_format``)."""

    FHIR = "FHIR"
    CSV = "CSV"


class DataOrigin(StrEnum):
    """Declared origin. ``SIMULATED`` only enters a clinic with ``is_demo``."""

    REAL = "REAL"
    SIMULATED = "SIMULATED"


class BatchStatus(StrEnum):
    """Status of a batch (``clinic.import_batches.status``)."""

    PREVIEWED = "PREVIEWED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class RowStatus(StrEnum):
    """Stored result of a row (``clinic.import_rows.status``)."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    REJECTED = "REJECTED"
    WARNING = "WARNING"
    UNSUPPORTED = "UNSUPPORTED"


class RowVerdict(StrEnum):
    """What the preview decided about one row, before anything is stored.

    ``VALID`` and ``WARNING`` rows are staged and only become patients at
    confirmation, so they never reach ``clinic.import_rows`` as previewed rows.
    """

    VALID = "VALID"
    WARNING = "WARNING"
    ERROR = "ERROR"
    DUPLICATE = "DUPLICATE"
    UNSUPPORTED = "UNSUPPORTED"


class DocumentType(StrEnum):
    """Identity document types (``clinic.patients.document_type``)."""

    CC = "CC"
    TI = "TI"
    RC = "RC"
    CE = "CE"
    PA = "PA"
    PEP = "PEP"
    PPT = "PPT"


class Sex(StrEnum):
    """Administrative sex (``clinic.patients.sex``)."""

    FEMALE = "FEMALE"
    MALE = "MALE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DiabetesType(StrEnum):
    """Type of diabetes (``clinic.patients.diabetes_type``)."""

    T1D = "T1D"
    T2D = "T2D"
    GDM = "GDM"
    OTHER = "OTHER"


class ImportIssue(StrEnum):
    """Why a row was not accepted as it came, without any personal data."""

    MRN_MISSING = "MRN_MISSING"
    MRN_INVALID = "MRN_INVALID"
    MRN_DUPLICATE = "MRN_DUPLICATE"
    BIRTH_DATE_MISSING = "BIRTH_DATE_MISSING"
    BIRTH_DATE_INVALID = "BIRTH_DATE_INVALID"
    FULL_NAME_MISSING = "FULL_NAME_MISSING"
    FULL_NAME_TOO_LONG = "FULL_NAME_TOO_LONG"
    DOCUMENT_TYPE_MISSING = "DOCUMENT_TYPE_MISSING"
    DOCUMENT_TYPE_INVALID = "DOCUMENT_TYPE_INVALID"
    DOCUMENT_NUMBER_MISSING = "DOCUMENT_NUMBER_MISSING"
    DOCUMENT_NUMBER_INVALID = "DOCUMENT_NUMBER_INVALID"
    DOCUMENT_DUPLICATE = "DOCUMENT_DUPLICATE"
    CONTACT_EMAIL_INVALID = "CONTACT_EMAIL_INVALID"
    CONTACT_PHONE_INVALID = "CONTACT_PHONE_INVALID"
    SEX_UNKNOWN_VALUE = "SEX_UNKNOWN_VALUE"
    DIABETES_TYPE_UNKNOWN_VALUE = "DIABETES_TYPE_UNKNOWN_VALUE"
    CELL_TOO_LONG = "CELL_TOO_LONG"
    RESOURCE_UNSUPPORTED = "RESOURCE_UNSUPPORTED"
    SOURCE_ROW_INVALID = "SOURCE_ROW_INVALID"

    @property
    def column(self) -> str:
        """The column (or source element) the error report names for this issue."""
        return _COLUMN_BY_ISSUE.get(self, ROW_COLUMN)


ROW_COLUMN: Final = "row"
"""Column named by issues that concern the whole row."""

_COLUMN_BY_ISSUE: Final[MappingProxyType[ImportIssue, str]] = MappingProxyType(
    {
        ImportIssue.MRN_MISSING: "mrn",
        ImportIssue.MRN_INVALID: "mrn",
        ImportIssue.MRN_DUPLICATE: "mrn",
        ImportIssue.BIRTH_DATE_MISSING: "birth_date",
        ImportIssue.BIRTH_DATE_INVALID: "birth_date",
        ImportIssue.FULL_NAME_MISSING: "full_name",
        ImportIssue.FULL_NAME_TOO_LONG: "full_name",
        ImportIssue.DOCUMENT_TYPE_MISSING: "document_type",
        ImportIssue.DOCUMENT_TYPE_INVALID: "document_type",
        ImportIssue.DOCUMENT_NUMBER_MISSING: "document_number",
        ImportIssue.DOCUMENT_NUMBER_INVALID: "document_number",
        ImportIssue.DOCUMENT_DUPLICATE: "document_number",
        ImportIssue.CONTACT_EMAIL_INVALID: "contact_email",
        ImportIssue.CONTACT_PHONE_INVALID: "contact_phone",
        ImportIssue.SEX_UNKNOWN_VALUE: "sex",
        ImportIssue.DIABETES_TYPE_UNKNOWN_VALUE: "diabetes_type",
        ImportIssue.RESOURCE_UNSUPPORTED: "resourceType",
    }
)

WARNING_ISSUES: Final[frozenset[ImportIssue]] = frozenset(
    {
        ImportIssue.CONTACT_EMAIL_INVALID,
        ImportIssue.CONTACT_PHONE_INVALID,
        ImportIssue.SEX_UNKNOWN_VALUE,
        ImportIssue.DIABETES_TYPE_UNKNOWN_VALUE,
    }
)
"""Issues that do not stop a patient from being created (the value is dropped)."""

STORED_RESOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"Patient", "Practitioner", "Condition", "Observation", "MedicationRequest"}
)
"""FHIR resource types ``clinic.import_rows`` accepts; any other is stored as NULL."""

CSV_REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "mrn",
    "birth_date",
    "full_name",
    "document_type",
    "document_number",
)
"""Columns a patient CSV must have; a missing one is a ``422``."""

CSV_OPTIONAL_COLUMNS: Final[tuple[str, ...]] = (
    "sex",
    "diabetes_type",
    "contact_email",
    "contact_phone",
)
"""Columns a patient CSV may have."""

CSV_COLUMNS: Final[tuple[str, ...]] = CSV_REQUIRED_COLUMNS + CSV_OPTIONAL_COLUMNS
"""Every column of the patient CSV, in the order of the template."""
