"""Canonical error responses of the API and the handlers that produce them.

Every error leaves the API as ``{"error": {"code", "message", "detail"}}``. The
mapping from ``ErrorCode`` to HTTP status lives only here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Final, cast, final

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from starlette.exceptions import HTTPException as StarletteHTTPException

from insumap.api.correlation import REQUEST_ID_HEADER, REQUEST_ID_STATE_KEY
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.i18n import MessageCatalog, MessageRenderError, MissingMessageError

logger = logging.getLogger(__name__)

FIELD_PATH_SEPARATOR = "."

STATUS_BY_CODE: Final[Mapping[ErrorCode, HTTPStatus]] = {
    ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.UNAUTHENTICATED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.FORBIDDEN: HTTPStatus.FORBIDDEN,
    ErrorCode.CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.PAYLOAD_TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
    ErrorCode.SESSION_REVOKED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.INVALID_CREDENTIALS: HTTPStatus.UNAUTHORIZED,
    ErrorCode.ACCOUNT_NOT_ACTIVE: HTTPStatus.FORBIDDEN,
    ErrorCode.CLINIC_SUSPENDED: HTTPStatus.FORBIDDEN,
    ErrorCode.MFA_REQUIRED: HTTPStatus.FORBIDDEN,
    ErrorCode.CONSENT_REQUIRED: HTTPStatus.FORBIDDEN,
    ErrorCode.EMAIL_UNAVAILABLE: HTTPStatus.CONFLICT,
    ErrorCode.CONSENT_VERSION_OUTDATED: HTTPStatus.CONFLICT,
    ErrorCode.INVALID_STATE_TRANSITION: HTTPStatus.CONFLICT,
    ErrorCode.INVITATION_INVALID: HTTPStatus.GONE,
}
"""HTTP status of every error code."""

CODE_BY_HTTP_STATUS: Final[Mapping[int, ErrorCode]] = {
    HTTPStatus.BAD_REQUEST: ErrorCode.VALIDATION_ERROR,
    HTTPStatus.UNAUTHORIZED: ErrorCode.UNAUTHENTICATED,
    HTTPStatus.FORBIDDEN: ErrorCode.FORBIDDEN,
    HTTPStatus.NOT_FOUND: ErrorCode.NOT_FOUND,
    # No code fits 405; like CAUDAL, an unsupported method reads as not found.
    HTTPStatus.METHOD_NOT_ALLOWED: ErrorCode.NOT_FOUND,
    HTTPStatus.CONFLICT: ErrorCode.CONFLICT,
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: ErrorCode.PAYLOAD_TOO_LARGE,
    HTTPStatus.UNPROCESSABLE_ENTITY: ErrorCode.VALIDATION_ERROR,
    HTTPStatus.TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
}
"""Error code of the HTTP errors raised by FastAPI and Starlette themselves."""


def status_for(code: ErrorCode) -> HTTPStatus:
    """Return the HTTP status of an error code."""
    return STATUS_BY_CODE[code]


def code_for_http_status(status_code: int) -> ErrorCode:
    """Return the error code of an HTTP status raised by the framework."""
    if status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return ErrorCode.INTERNAL_ERROR
    return CODE_BY_HTTP_STATUS.get(status_code, ErrorCode.VALIDATION_ERROR)


class ErrorBody(BaseModel):
    """Content of an error response."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode = Field(
        description="Código estable del error, en inglés.", examples=["NOT_FOUND"]
    )
    message: str = Field(
        description="Mensaje en español para la persona usuaria.",
        examples=["El recurso solicitado no existe."],
    )
    detail: dict[str, JsonValue] = Field(
        default_factory=dict,
        description=(
            "Datos adicionales sin información personal. Los errores de validación "
            "van en 'errors', con la ruta del campo y el tipo de error."
        ),
    )


class ErrorResponse(BaseModel):
    """Canonical error response of the API."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


@final
class ErrorResponseFactory:
    """Builds canonical error responses with their Spanish message.

    If a message key is missing from the catalog, or its parameters are
    incomplete, the response falls back to the default message of the code
    instead of failing.
    """

    def __init__(self, catalog: MessageCatalog) -> None:
        self._catalog = catalog

    def create(
        self,
        code: ErrorCode,
        *,
        message_key: str | None = None,
        params: Mapping[str, object] | None = None,
        detail: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        """Return the response of ``code`` with its HTTP status."""
        body = ErrorResponse(
            error=ErrorBody(
                code=code,
                message=self._message(code, message_key, params or {}),
                detail=jsonable_encoder(dict(detail or {})),
            )
        )
        return JSONResponse(
            status_code=status_for(code),
            content=body.model_dump(mode="json"),
            headers=dict(headers) if headers else None,
        )

    def _message(
        self, code: ErrorCode, message_key: str | None, params: Mapping[str, object]
    ) -> str:
        key = message_key or code.default_message_key
        try:
            return self._catalog.render(key, **params)
        except (MissingMessageError, MessageRenderError):
            logger.warning("Message %s could not be rendered; using the default", key)
            return self._catalog.render(code.default_message_key)


@final
class ApiExceptionHandlers:
    """Turns every exception that leaves a route into the canonical error format.

    Validation details carry only field paths and error types, never the rejected
    values, and unexpected errors answer ``500 INTERNAL_ERROR`` without traces.
    """

    def __init__(self, responses: ErrorResponseFactory) -> None:
        self._responses = responses

    def install(self, app: FastAPI) -> None:
        """Register the handlers on ``app``."""
        app.add_exception_handler(InsumapError, self.handle_insumap_error)
        app.add_exception_handler(RequestValidationError, self.handle_validation_error)
        app.add_exception_handler(StarletteHTTPException, self.handle_http_exception)
        app.add_exception_handler(Exception, self.handle_unexpected_error)

    async def handle_insumap_error(
        self, request: Request, exc: Exception
    ) -> JSONResponse:
        """Answer a business error with its code, message and detail."""
        error = cast(InsumapError, exc)
        return self._responses.create(
            error.code,
            message_key=error.message_key,
            params=error.params,
            detail=error.detail,
            headers=error.headers or None,
        )

    async def handle_validation_error(
        self, request: Request, exc: Exception
    ) -> JSONResponse:
        """Answer ``422 VALIDATION_ERROR`` listing the invalid fields."""
        error = cast(RequestValidationError, exc)
        fields = [
            {
                "field": FIELD_PATH_SEPARATOR.join(str(part) for part in item["loc"]),
                "type": str(item["type"]),
            }
            for item in error.errors()
        ]
        return self._responses.create(
            ErrorCode.VALIDATION_ERROR, detail={"errors": fields}
        )

    async def handle_http_exception(
        self, request: Request, exc: Exception
    ) -> JSONResponse:
        """Answer the HTTP errors of the framework (unknown route, bad method)."""
        error = cast(StarletteHTTPException, exc)
        code = code_for_http_status(error.status_code)
        keeps_status = status_for(code) == error.status_code
        return self._responses.create(
            code, headers=error.headers if keeps_status else None
        )

    async def handle_unexpected_error(
        self, request: Request, exc: Exception
    ) -> JSONResponse:
        """Log the failure and answer ``500 INTERNAL_ERROR`` with no details.

        This handler runs outside the user middleware, so it takes the request id
        from ``request.state`` to log it and echo it in ``X-Request-ID``.
        """
        request_id = getattr(request.state, REQUEST_ID_STATE_KEY, None)
        logger.error(
            "Unhandled error while processing the request",
            exc_info=exc,
            extra={REQUEST_ID_STATE_KEY: request_id},
        )
        headers = {REQUEST_ID_HEADER: request_id} if request_id else None
        return self._responses.create(ErrorCode.INTERNAL_ERROR, headers=headers)
