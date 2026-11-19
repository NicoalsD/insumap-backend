"""Documented error responses of the records and metrics endpoints."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Final

from insumap.api.errors import ErrorResponse

type Responses = dict[int | str, dict[str, Any]]

ERROR_DESCRIPTIONS: Final[dict[int, str]] = {
    HTTPStatus.UNAUTHORIZED: "`UNAUTHENTICATED` o `SESSION_REVOKED`.",
    HTTPStatus.FORBIDDEN: (
        "`FORBIDDEN`, `CLINIC_SUSPENDED`, `MFA_REQUIRED` (personal) o "
        "`CONSENT_REQUIRED` (paciente)."
    ),
    HTTPStatus.NOT_FOUND: (
        "`NOT_FOUND`: el recurso no existe, es de otra clínica o el paciente no "
        "está asignado (el mismo cuerpo en los tres casos)."
    ),
    HTTPStatus.CONFLICT: (
        "`CONFLICT` (mismo identificador con otro contenido) o "
        "`INVALID_STATE_TRANSITION` (el registro ya fue corregido o anulado)."
    ),
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "`PAYLOAD_TOO_LARGE`.",
    HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "`UNSUPPORTED_MEDIA_TYPE`.",
    HTTPStatus.UNPROCESSABLE_ENTITY: (
        "`VALIDATION_ERROR`, `GLUCOSE_OUT_OF_RANGE`, `READING_IN_FUTURE`, "
        "`READING_TOO_OLD` o `REASON_REQUIRED`."
    ),
    HTTPStatus.TOO_MANY_REQUESTS: "`RATE_LIMITED`, con el encabezado `Retry-After`.",
}

COMMON: Final = (
    HTTPStatus.UNAUTHORIZED,
    HTTPStatus.FORBIDDEN,
    HTTPStatus.UNPROCESSABLE_ENTITY,
)


def records_error_responses(*extra: HTTPStatus) -> Responses:
    """Document the canonical error body of the common statuses plus ``extra``."""
    statuses = dict.fromkeys((*COMMON, *extra, HTTPStatus.TOO_MANY_REQUESTS))
    return {
        int(status): {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[status]}
        for status in statuses
    }
