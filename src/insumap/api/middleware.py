"""ASGI middleware of the API: correlation id and request body size limit."""

from __future__ import annotations

import contextlib
import re
import uuid
from typing import Final, final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from insumap.api.correlation import REQUEST_ID_HEADER, REQUEST_ID_STATE_KEY
from insumap.api.errors import ErrorResponseFactory
from insumap.shared.errors import ErrorCode
from insumap.shared.field_limits import FieldLimits
from insumap.shared.request_context import bind_request_id, unbind_request_id

HTTP_SCOPE: Final = "http"
HTTP_REQUEST_MESSAGE: Final = "http.request"
HTTP_RESPONSE_START_MESSAGE: Final = "http.response.start"
CONTENT_LENGTH_HEADER: Final = "content-length"
EMPTY_BODY: Final = b""
STATE_SCOPE_KEY: Final = "state"
SAFE_REQUEST_ID: Final = re.compile(FieldLimits.REQUEST_ID_PATTERN)


@final
class RequestIdMiddleware:
    """Gives every request a correlation id and echoes it in ``X-Request-ID``.

    A client supplied id is kept only if it fits ``REQUEST_ID_MAX_LENGTH`` and
    matches ``REQUEST_ID_PATTERN``; otherwise a new UUID4 replaces it. The id is
    bound for the logs and stored in ``request.state``, where the handler of
    unexpected errors (which runs outside the user middleware) finds it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE:
            await self._app(scope, receive, send)
            return
        request_id = self.accept_or_generate(
            Headers(scope=scope).get(REQUEST_ID_HEADER)
        )
        scope.setdefault(STATE_SCOPE_KEY, {})[REQUEST_ID_STATE_KEY] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        token = bind_request_id(request_id)
        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            unbind_request_id(token)

    @staticmethod
    def accept_or_generate(candidate: str | None) -> str:
        """Return ``candidate`` if it is a safe id, else a new UUID4."""
        if (
            candidate is not None
            and len(candidate) <= FieldLimits.REQUEST_ID_MAX_LENGTH
            and SAFE_REQUEST_ID.fullmatch(candidate)
        ):
            return candidate
        return str(uuid.uuid4())


class _BodyTooLargeError(Exception):
    """Raised while reading a body once it goes past the limit."""


@final
class BodySizeLimitMiddleware:
    """Rejects request bodies larger than the limit with ``413 PAYLOAD_TOO_LARGE``.

    The declared ``Content-Length`` is checked before the app runs. Bodies sent
    without it (chunked) are counted while they are read: past the limit, any
    response the app tries to send is dropped and the 413 is sent instead,
    unless the app had already started its response.
    """

    def __init__(
        self, app: ASGIApp, *, responses: ErrorResponseFactory, max_body_bytes: int
    ) -> None:
        self._app = app
        self._responses = responses
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE:
            await self._app(scope, receive, send)
            return
        if self._declared_size_exceeds_limit(scope):
            await self._reject(scope, receive, send)
            return

        received_bytes = 0
        body_too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes, body_too_large
            message = await receive()
            if message["type"] == HTTP_REQUEST_MESSAGE:
                received_bytes += len(message.get("body", EMPTY_BODY))
                if received_bytes > self._max_body_bytes:
                    body_too_large = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if body_too_large and not response_started:
                return
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                response_started = True
            await send(message)

        # A route reading the body by hand lets the error escape; FastAPI turns
        # it into its own 400, which guarded_send drops. Both end in the 413.
        with contextlib.suppress(_BodyTooLargeError):
            await self._app(scope, limited_receive, guarded_send)
        if body_too_large and not response_started:
            await self._reject(scope, receive, send)

    def _declared_size_exceeds_limit(self, scope: Scope) -> bool:
        declared = Headers(scope=scope).get(CONTENT_LENGTH_HEADER)
        return (
            declared is not None
            and declared.isdigit()
            and int(declared) > self._max_body_bytes
        )

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = self._responses.create(
            ErrorCode.PAYLOAD_TOO_LARGE, detail={"max_bytes": self._max_body_bytes}
        )
        await response(scope, receive, send)
