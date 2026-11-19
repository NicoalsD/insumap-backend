"""Error codes and the base class of every business error."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

KEY_SEPARATOR = "_"
KEY_DOMAIN_SEPARATOR = "."


class ErrorCode(StrEnum):
    """Stable error codes of the API, in English upper snake case.

    Clients decide what to do from the code, never from the text. The Spanish text
    of each code lives in ``messages_es.json`` under ``default_message_key`` and
    the HTTP status is assigned only by the api layer.
    """

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SESSION_REVOKED = "SESSION_REVOKED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_NOT_ACTIVE = "ACCOUNT_NOT_ACTIVE"
    CLINIC_SUSPENDED = "CLINIC_SUSPENDED"
    MFA_REQUIRED = "MFA_REQUIRED"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    EMAIL_UNAVAILABLE = "EMAIL_UNAVAILABLE"
    CONSENT_VERSION_OUTDATED = "CONSENT_VERSION_OUTDATED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    INVITATION_INVALID = "INVITATION_INVALID"
    REASON_REQUIRED = "REASON_REQUIRED"

    @property
    def default_message_key(self) -> str:
        """Key of the default message: ``NOT_FOUND`` uses ``not.found``.

        The first word is the domain and the rest goes after the dot, so
        ``PAYLOAD_TOO_LARGE`` uses ``payload.too_large`` and a single word such
        as ``CONFLICT`` uses ``conflict``.
        """
        domain, _, rest = self.value.lower().partition(KEY_SEPARATOR)
        return f"{domain}{KEY_DOMAIN_SEPARATOR}{rest}" if rest else domain


class InsumapError(Exception):
    """Base of every business error: an ``ErrorCode`` plus a message key.

    ``message_key`` points to the Spanish text in ``messages_es.json`` (the code's
    default when omitted) and ``params`` fills its placeholders. ``detail`` is
    returned to the client as is, so it must never hold personal or health data.
    ``headers`` are HTTP headers the api layer adds to the response (for
    example ``Retry-After``). The string form of the error is the message key,
    never the parameters.
    """

    def __init__(
        self,
        code: ErrorCode,
        *,
        message_key: str | None = None,
        params: Mapping[str, object] | None = None,
        detail: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message_key = message_key or code.default_message_key
        self.params: Mapping[str, object] = MappingProxyType(dict(params or {}))
        self.detail: Mapping[str, object] = MappingProxyType(dict(detail or {}))
        self.headers: Mapping[str, str] = MappingProxyType(dict(headers or {}))
        super().__init__(self.message_key)
