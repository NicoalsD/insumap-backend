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

    # Requests and pagination.

    MAX_REQUEST_BODY_BYTES: ClassVar[int] = 1024 * 1024
    """Maximum size of a request body, in bytes (1 MiB)."""

    PAGE_SIZE_DEFAULT: ClassVar[int] = 20
    """Page size used when the client does not ask for one."""

    PAGE_SIZE_MAX: ClassVar[int] = 100
    """Largest page size a client may ask for."""
