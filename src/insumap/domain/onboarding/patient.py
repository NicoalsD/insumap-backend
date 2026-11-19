"""Rules that decide whether a source row can become a patient.

Pure Python: the caller passes the reference date (``today``), so no rule reads
the system clock. Limits come from ``FieldLimits``; no clinical value lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Final

from insumap.domain.onboarding.vocabulary import (
    DiabetesType,
    DocumentType,
    ImportIssue,
    Sex,
)
from insumap.shared.field_limits import FieldLimits

ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
MRN_SHAPE: Final = re.compile(FieldLimits.MRN_PATTERN)
DOCUMENT_SHAPE: Final = re.compile(FieldLimits.DOCUMENT_NUMBER_PATTERN)
EMAIL_SHAPE: Final = re.compile(FieldLimits.EMAIL_PATTERN)
IGNORED_IN_DOCUMENT: Final = frozenset({" ", "."})
"""Separators people type in a document number; they are not part of it."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientCandidate:
    """The raw fields a source row gives, as text. Nothing is checked yet."""

    mrn: str | None = None
    birth_date: str | None = None
    full_name: str | None = None
    document_type: str | None = None
    document_number: str | None = None
    sex: str | None = None
    diabetes_type: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedPatient:
    """A patient whose required fields passed every rule. The document is normalized.

    ``document_number`` is the plain number: it only lives in memory until it is
    sealed (AES-GCM) and hashed (HMAC). Never log it or return it.
    """

    mrn: str
    full_name: str
    birth_date: date
    document_type: DocumentType
    document_number: str
    document_last4: str
    sex: Sex
    diabetes_type: DiabetesType
    contact_email: str | None
    contact_phone: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationResult:
    """Errors stop the row; warnings keep the row and drop only the bad value."""

    errors: tuple[ImportIssue, ...]
    warnings: tuple[ImportIssue, ...]
    patient: ValidatedPatient | None


def normalize_document_number(raw: str) -> str:
    """Upper case, without spaces and dots (``cc 1.020-304`` becomes ``CC1020-304``)."""
    return "".join(char for char in raw.upper() if char not in IGNORED_IN_DOCUMENT)


def validate_patient(candidate: PatientCandidate, *, today: date) -> ValidationResult:
    """Apply every rule of the import to one candidate, collecting all the issues."""
    errors: list[ImportIssue] = []
    warnings: list[ImportIssue] = []

    mrn = _mrn(candidate.mrn, errors)
    birth_date = _birth_date(candidate.birth_date, today=today, errors=errors)
    full_name = _name(candidate.full_name, errors)
    document_type = _document_type(candidate.document_type, errors)
    document_number = _document_number(candidate.document_number, errors)

    sex = _sex(candidate.sex, warnings)
    diabetes_type = _diabetes_type(candidate.diabetes_type, warnings)
    contact_email = _email(candidate.contact_email, warnings)
    contact_phone = _phone(candidate.contact_phone, warnings)

    if (
        errors
        or mrn is None
        or birth_date is None
        or full_name is None
        or document_type is None
        or document_number is None
    ):
        return ValidationResult(
            errors=tuple(errors), warnings=tuple(warnings), patient=None
        )
    patient = ValidatedPatient(
        mrn=mrn,
        full_name=full_name,
        birth_date=birth_date,
        document_type=document_type,
        document_number=document_number,
        document_last4=document_number[-FieldLimits.DOCUMENT_LAST4_LENGTH :],
        sex=sex,
        diabetes_type=diabetes_type,
        contact_email=contact_email,
        contact_phone=contact_phone,
    )
    return ValidationResult(errors=(), warnings=tuple(warnings), patient=patient)


def _text(raw: str | None) -> str | None:
    """Trimmed text, or ``None`` when empty."""
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def _mrn(raw: str | None, errors: list[ImportIssue]) -> str | None:
    text = _text(raw)
    if text is None:
        errors.append(ImportIssue.MRN_MISSING)
        return None
    if len(text) > FieldLimits.MRN_MAX_LENGTH or MRN_SHAPE.fullmatch(text) is None:
        errors.append(ImportIssue.MRN_INVALID)
        return None
    return text


def _birth_date(
    raw: str | None, *, today: date, errors: list[ImportIssue]
) -> date | None:
    text = _text(raw)
    if text is None:
        errors.append(ImportIssue.BIRTH_DATE_MISSING)
        return None
    parsed = _parse_iso_date(text)
    if (
        parsed is None
        or parsed > today
        or parsed.year < FieldLimits.BIRTH_DATE_MIN_YEAR
    ):
        errors.append(ImportIssue.BIRTH_DATE_INVALID)
        return None
    return parsed


def _parse_iso_date(text: str) -> date | None:
    if ISO_DATE.fullmatch(text) is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _name(raw: str | None, errors: list[ImportIssue]) -> str | None:
    text = _text(raw)
    if text is None:
        errors.append(ImportIssue.FULL_NAME_MISSING)
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) > FieldLimits.PATIENT_FULL_NAME_MAX_LENGTH:
        errors.append(ImportIssue.FULL_NAME_TOO_LONG)
        return None
    return collapsed


def _document_type(raw: str | None, errors: list[ImportIssue]) -> DocumentType | None:
    text = _text(raw)
    if text is None:
        errors.append(ImportIssue.DOCUMENT_TYPE_MISSING)
        return None
    try:
        return DocumentType(text.upper())
    except ValueError:
        errors.append(ImportIssue.DOCUMENT_TYPE_INVALID)
        return None


def _document_number(raw: str | None, errors: list[ImportIssue]) -> str | None:
    text = _text(raw)
    if text is None:
        errors.append(ImportIssue.DOCUMENT_NUMBER_MISSING)
        return None
    normalized = normalize_document_number(text)
    long_enough = len(normalized) >= FieldLimits.DOCUMENT_NUMBER_MIN_LENGTH
    short_enough = len(normalized) <= FieldLimits.DOCUMENT_NUMBER_MAX_LENGTH
    if (
        not (long_enough and short_enough)
        or DOCUMENT_SHAPE.fullmatch(normalized) is None
    ):
        errors.append(ImportIssue.DOCUMENT_NUMBER_INVALID)
        return None
    return normalized


def _sex(raw: str | None, warnings: list[ImportIssue]) -> Sex:
    """Database codes and FHIR genders share their words once upper cased."""
    text = _text(raw)
    if text is None:
        return Sex.UNKNOWN
    try:
        return Sex(text.upper())
    except ValueError:
        warnings.append(ImportIssue.SEX_UNKNOWN_VALUE)
        return Sex.UNKNOWN


def _diabetes_type(raw: str | None, warnings: list[ImportIssue]) -> DiabetesType:
    text = _text(raw)
    if text is None:
        return DiabetesType.OTHER
    try:
        return DiabetesType(text.upper())
    except ValueError:
        warnings.append(ImportIssue.DIABETES_TYPE_UNKNOWN_VALUE)
        return DiabetesType.OTHER


def _email(raw: str | None, warnings: list[ImportIssue]) -> str | None:
    text = _text(raw)
    if text is None:
        return None
    lowered = text.lower()
    if (
        len(lowered) > FieldLimits.EMAIL_MAX_LENGTH
        or EMAIL_SHAPE.fullmatch(lowered) is None
    ):
        warnings.append(ImportIssue.CONTACT_EMAIL_INVALID)
        return None
    return lowered


def _phone(raw: str | None, warnings: list[ImportIssue]) -> str | None:
    text = _text(raw)
    if text is None:
        return None
    if len(text) > FieldLimits.PATIENT_PHONE_MAX_LENGTH:
        warnings.append(ImportIssue.CONTACT_PHONE_INVALID)
        return None
    return text
