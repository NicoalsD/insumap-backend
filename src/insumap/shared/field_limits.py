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

    PASSWORD_MIN_LENGTH: ClassVar[int] = 12
    """Minimum length of a new password."""

    PASSWORD_MAX_LENGTH: ClassVar[int] = 128
    """Maximum length of any password input, checked before hashing."""

    # Requests and pagination.

    MAX_REQUEST_BODY_BYTES: ClassVar[int] = 1024 * 1024
    """Maximum size of a request body, in bytes (1 MiB)."""

    PAGE_SIZE_DEFAULT: ClassVar[int] = 20
    """Page size used when the client does not ask for one."""

    PAGE_SIZE_MAX: ClassVar[int] = 100
    """Largest page size a client may ask for."""
