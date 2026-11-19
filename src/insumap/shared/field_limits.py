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

    CREDENTIAL_BATCH_MAX_ITEMS: ClassVar[int] = 100
    """Patients in one credential batch (``Seguridad.md`` 3.3)."""

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

    # Alerts (alerts.alert_rules and alerts.alerts).

    ALERT_NAME_MAX_LENGTH: ClassVar[int] = 120
    """Maximum length of the name of an alert rule (``alerts.alert_rules.name``)."""

    ALERT_LEVEL_MIN: ClassVar[int] = 1
    """Lowest hypoglycemia level (``alerts.alert_rules.level``, CHECK 1 to 3)."""

    ALERT_LEVEL_MAX: ClassVar[int] = 3
    """Highest hypoglycemia level, and the last step of an escalation chain."""

    ALERT_MINUTES_MIN: ClassVar[int] = 1
    """Shortest duration or wait of a rule, in minutes."""

    ALERT_MINUTES_MAX: ClassVar[int] = 10080
    """Longest duration or wait of a rule, in minutes (one week)."""

    ALERT_RATE_INPUT_MAX: ClassVar[int] = 100
    """Largest rate of change accepted in a rule, in mg/dL per minute."""

    ALERT_CONDITION_MAX_DEPTH: ClassVar[int] = 4
    """Deepest nesting of a rule condition tree (an input limit, not a clinical one)."""

    ALERT_CONDITION_MAX_NODES: ClassVar[int] = 16
    """Most nodes, leaves and groups together, in one rule condition tree."""

    # Treatment plans and protocol templates (care schema).

    TEMPLATE_NAME_MAX_LENGTH: ClassVar[int] = 120
    """Maximum length of a protocol template name (``protocol_templates.name``)."""

    TEMPLATE_CODE_MAX_LENGTH: ClassVar[int] = 40
    """Maximum length of a protocol template code (``protocol_templates.code``)."""

    PLAN_ITEM_NAME_MAX_LENGTH: ClassVar[int] = 120
    """Maximum length of a plan item name (``treatment_plan_items.name``)."""

    INSTRUCTIONS_MAX_LENGTH: ClassVar[int] = 500
    """Maximum length of the instructions of an item or of a template's description."""

    PLAN_NOTES_MAX_LENGTH: ClassVar[int] = 1000
    """Maximum length of the notes of a plan (``care.treatment_plans.notes``)."""

    PLAN_ITEMS_MAX_ITEMS: ClassVar[int] = 100
    """Most items one plan or template may list (a technical bound of the request)."""

    # Plan de tratamiento, metas y recordatorios (API.md 8.7). Columnas:
    # care.target_profiles.code, label, source_reference; care.reminder_schedules.
    TARGET_PROFILE_CODE_MAX_LENGTH: ClassVar[int] = 40
    """``care.target_profiles.code`` (varchar(40))."""

    TARGET_PROFILE_CODE_PATTERN: ClassVar[str] = r"^[A-Z][A-Z0-9_]*$"
    """Upper snake case, as the ``ck_target_profiles_code`` CHECK requires."""

    PROFILE_LABEL_MAX_LENGTH: ClassVar[int] = 120
    """``care.target_profiles.label`` (varchar(120))."""

    SOURCE_REFERENCE_MAX_LENGTH: ClassVar[int] = 300
    """``care.target_profiles.source_reference`` (varchar(300))."""

    SMALLINT_MAX: ClassVar[int] = 32767
    """Largest value of a ``smallint`` column (``min_days`` and the minutes)."""

    TARGET_MG_DL_MAX: ClassVar[int] = 9999
    """Largest glucose threshold of a profile: ``numeric(5,1)`` columns."""

    INTEGER_MAX: ClassVar[int] = 2147483647
    """Largest value of an ``integer`` column (minimum readings for the CV)."""

    # Notifications (alerts.push_subscriptions and alerts.notification_preferences).

    PUSH_ENDPOINT_MAX_LENGTH: ClassVar[int] = 2048
    """Longest Web Push endpoint URL (``alerts.push_subscriptions.endpoint``)."""

    PUSH_ENDPOINT_PATTERN: ClassVar[str] = r"^https://[^\s]+$"
    """A Web Push endpoint is an https URL without spaces (use fullmatch)."""

    PUSH_KEY_MAX_LENGTH: ClassVar[int] = 255
    """Longest public key of a subscription (``alerts.push_subscriptions.p256dh``)."""

    PUSH_AUTH_SECRET_MAX_LENGTH: ClassVar[int] = 64
    """Longest auth secret of a subscription, before it is encrypted."""

    PUSH_KEY_PATTERN: ClassVar[str] = r"^[A-Za-z0-9_-]+$"
    """Subscription keys are base64url without padding (use fullmatch)."""

    # Audit (audit.audit_log and audit.data_access_log, API.md 8.13).

    AUDIT_ACTION_MAX_LENGTH: ClassVar[int] = 60
    """Longest action name of ``audit.audit_log.action`` (``varchar(60)``)."""

    AUDIT_ACTION_PATTERN: ClassVar[str] = r"^[A-Z][A-Z0-9_]*$"
    """Action names are UPPER_SNAKE_CASE (``ck_audit_log_action``; use fullmatch)."""
