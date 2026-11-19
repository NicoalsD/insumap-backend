"""Technical and security limits of the API."""

from typing import ClassVar, final


@final
class FieldLimits:
    """Single source of technical and security limits (lengths, patterns, sizes).

    Pydantic ``Field(...)`` declarations, middleware and pagination read these
    constants; no other module writes a limit as a literal. A drift test compares
    the lengths with ``information_schema`` of the schema pinned in
    ``db-schema.lock``. Clinical and business parameters never live here: they
    are versioned data in the database.
    """

    # Correlation id.

    REQUEST_ID_MAX_LENGTH: ClassVar[int] = 64
    """Maximum length of a client supplied ``X-Request-ID``."""

    REQUEST_ID_PATTERN: ClassVar[str] = (
        rf"^[A-Za-z0-9._-]{{1,{REQUEST_ID_MAX_LENGTH}}}$"
    )
    """Characters accepted in a client supplied ``X-Request-ID`` (use fullmatch)."""

    # Accounts.

    EMAIL_MAX_LENGTH: ClassVar[int] = 254
    """Maximum length of an email address (RFC 5321 path limit)."""

    EMAIL_PATTERN: ClassVar[str] = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    """Shape of an email typed by a person (use fullmatch); not a delivery check."""

    PASSWORD_MIN_LENGTH: ClassVar[int] = 12
    """Minimum length of a new password."""

    PASSWORD_MAX_LENGTH: ClassVar[int] = 128
    """Maximum length of any password input, checked before hashing."""

    # Authentication.

    AUTH_HEADER_MAX_BYTES: ClassVar[int] = 2048
    """Largest ``Authorization`` header accepted; longer ones are never decoded."""

    OPAQUE_TOKEN_MAX_LENGTH: ClassVar[int] = 64
    """Maximum length of an opaque token input (challenge or activation token)."""

    TOTP_CODE_LENGTH: ClassVar[int] = 6
    """Digits of a TOTP code (RFC 6238)."""

    MFA_CODE_INPUT_MAX_LENGTH: ClassVar[int] = 16
    """Maximum length of an MFA code input: a TOTP or a formatted recovery code."""

    RECOVERY_CODE_LENGTH: ClassVar[int] = 10
    """Characters of a normalized MFA recovery code (Crockford base32, 50 bits)."""

    RECOVERY_CODE_GROUP_SIZE: ClassVar[int] = 5
    """Characters per dash separated group of a displayed recovery code."""

    # Activation.

    ACTIVATION_CODE_LENGTH: ClassVar[int] = 16
    """Characters of a normalized activation code (Crockford base32, 80 bits)."""

    ACTIVATION_CODE_GROUP_SIZE: ClassVar[int] = 4
    """Characters per dash separated group of a displayed activation code."""

    ACTIVATION_CODE_INPUT_MAX_LENGTH: ClassVar[int] = 32
    """Maximum length of a raw activation code input, with dashes and spaces."""

    BIRTH_DATE_MIN_YEAR: ClassVar[int] = 1900
    """Earliest year accepted in a birth date input."""

    # Decisions.

    REASON_MIN_LENGTH: ClassVar[int] = 10
    """Shortest reason that accompanies a suspension, withdrawal or correction."""

    REASON_MAX_LENGTH: ClassVar[int] = 500
    """Longest reason that accompanies a decision."""

    # Clinics and staff (lengths of ``clinic.clinics`` and ``clinic.staff_profiles``).

    CLINIC_NAME_MAX_LENGTH: ClassVar[int] = 120
    """Maximum length of the name of a clinic."""

    TAX_ID_MAX_LENGTH: ClassVar[int] = 32
    """Maximum length of the tax identifier of a clinic."""

    TIMEZONE_MAX_LENGTH: ClassVar[int] = 64
    """Maximum length of an IANA time zone name."""

    SITE_NAME_MAX_LENGTH: ClassVar[int] = 120
    """Maximum length of the name of a site."""

    STAFF_FULL_NAME_MAX_LENGTH: ClassVar[int] = 120
    """Maximum length of the full name of a staff member."""

    PROFESSIONAL_LICENSE_MAX_LENGTH: ClassVar[int] = 40
    """Maximum length of a professional license number."""

    SPECIALTY_MAX_LENGTH: ClassVar[int] = 80
    """Maximum length of a medical specialty."""

    STAFF_SITES_MAX_ITEMS: ClassVar[int] = 50
    """Most sites one ``PUT /users/{user_id}/sites`` may list (a technical bound)."""

    # Requests and pagination.

    MAX_REQUEST_BODY_BYTES: ClassVar[int] = 1024 * 1024
    """Maximum size of a request body, in bytes (1 MiB)."""

    PAGE_SIZE_DEFAULT: ClassVar[int] = 20
    """Page size used when the client does not ask for one."""

    PAGE_SIZE_MAX: ClassVar[int] = 100
    """Largest page size a client may ask for."""

    # Patient records (monitoring schema).

    GLUCOSE_NOTE_MAX_LENGTH: ClassVar[int] = 500
    """Maximum length of the note of a glucose reading."""

    RECORD_NOTE_MAX_LENGTH: ClassVar[int] = 500
    """Maximum length of the note of an insulin dose, meal, activity or symptom."""

    INSULIN_PRODUCT_NAME_MAX_LENGTH: ClassVar[int] = 80
    """Maximum length of an insulin product name."""

    ACTIVITY_TYPE_MAX_LENGTH: ClassVar[int] = 40
    """Maximum length of a physical activity type."""

    SYMPTOM_CODE_MAX_LENGTH: ClassVar[int] = 32
    """Maximum length of a symptom catalog code."""

    GLUCOSE_VALUE_INPUT_MAX: ClassVar[int] = 9999
    """Largest glucose number accepted as input (the column is numeric(5,1)).

    The measurable range of the clinic is a clinical parameter in the database;
    this only protects the column.
    """

    INSULIN_UNITS_INPUT_MAX: ClassVar[int] = 1000
    """Largest number of insulin units accepted in one record."""

    CARBS_G_INPUT_MAX: ClassVar[int] = 1000
    """Largest carbohydrate estimate, in grams, accepted in one meal."""

    ACTIVITY_DURATION_MINUTES_MAX: ClassVar[int] = 1440
    """Longest physical activity accepted, in minutes (one day)."""

    LAB_VALUE_INPUT_MAX: ClassVar[int] = 1000
    """Largest laboratory number accepted as input, in the unit sent."""

    READINGS_BATCH_MAX_ITEMS: ClassVar[int] = 500
    """Readings in one offline batch (Seguridad 13.3)."""

    READINGS_BATCH_MAX_BYTES: ClassVar[int] = 512 * 1024
    """Body size of one offline batch (512 KiB)."""

    CGM_CSV_MAX_BYTES: ClassVar[int] = 10 * 1024 * 1024
    """Body size of one CGM CSV import (10 MiB)."""

    CGM_CSV_MAX_ROWS: ClassVar[int] = 100_000
    """Rows of one CGM CSV import."""

    TIMELINE_EVENT_TYPES_MAX: ClassVar[int] = 5
    """Event types a timeline filter may list."""

    EXPORT_MAX_EVENTS: ClassVar[int] = 50_000
    """Events one timeline export may contain."""

    AGP_DAYS_MAX: ClassVar[int] = 90
    """Most days an AGP request may superimpose."""

    CURSOR_MAX_LENGTH: ClassVar[int] = 512
    """Longest pagination cursor accepted (the records cursor carries a time and
    an id); a longer one is invalid."""

    # Patient import (clinic.patients, clinic.import_rows and API.md 8.4).

    MRN_MAX_LENGTH: ClassVar[int] = 40
    """Maximum length of a medical record number (``clinic.patients.mrn``)."""

    MRN_PATTERN: ClassVar[str] = r"[A-Za-z0-9][A-Za-z0-9._/-]*"
    """Shape of a medical record number (use fullmatch)."""

    PATIENT_FULL_NAME_MAX_LENGTH: ClassVar[int] = 120
    """Maximum length of a patient's full name (``clinic.patients.full_name``)."""

    PATIENT_PHONE_MAX_LENGTH: ClassVar[int] = 32
    """Maximum length of a contact phone (``clinic.patients.contact_phone``)."""

    DOCUMENT_NUMBER_MIN_LENGTH: ClassVar[int] = 5
    """Shortest identity document number, after normalization."""

    DOCUMENT_NUMBER_MAX_LENGTH: ClassVar[int] = 20
    """Longest identity document number, after normalization."""

    DOCUMENT_NUMBER_PATTERN: ClassVar[str] = r"[A-Z0-9-]+"
    """Characters of a normalized document number (use fullmatch)."""

    DOCUMENT_LAST4_LENGTH: ClassVar[int] = 4
    """Characters kept in clear to show a masked document (``document_last4``)."""

    FHIR_BUNDLE_MAX_BYTES: ClassVar[int] = 10 * 1024 * 1024
    """Body size of one FHIR Bundle import (10 MiB)."""

    FHIR_BUNDLE_MAX_ENTRIES: ClassVar[int] = 5000
    """Entries of one FHIR Bundle import."""

    FHIR_BUNDLE_MAX_DEPTH: ClassVar[int] = 32
    """Nesting depth of one FHIR Bundle import."""

    PATIENT_CSV_MAX_BYTES: ClassVar[int] = 2 * 1024 * 1024
    """Body size of one patient CSV import (2 MiB)."""

    PATIENT_CSV_MAX_ROWS: ClassVar[int] = 5000
    """Data rows of one patient CSV import."""

    PATIENT_CSV_MAX_COLUMNS: ClassVar[int] = 40
    """Columns of one patient CSV import."""

    PATIENT_CSV_MAX_CELL_LENGTH: ClassVar[int] = 1000
    """Characters of one cell of a patient CSV import."""

    IMPORT_PREVIEW_MAX_AGE_MINUTES: ClassVar[int] = 60
    """How long a previewed batch waits for its confirmation before it expires."""
