"""ASGI middleware of the API: hosts, security headers, correlation id, body size."""

from __future__ import annotations

import contextlib
import re
import uuid
from collections.abc import Iterable, Mapping
from http import HTTPStatus
from typing import Final, final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from insumap.api.correlation import REQUEST_ID_HEADER, REQUEST_ID_STATE_KEY
from insumap.api.errors import ErrorResponseFactory
from insumap.api.openapi import DOCS_URL, OPENAPI_URL
from insumap.api.paths import API_V1_PREFIX
from insumap.shared.errors import ErrorCode
from insumap.shared.field_limits import FieldLimits
from insumap.shared.request_context import bind_request_id, unbind_request_id

HTTP_SCOPE: Final = "http"
HTTP_REQUEST_MESSAGE: Final = "http.request"
HTTP_RESPONSE_START_MESSAGE: Final = "http.response.start"
CONTENT_LENGTH_HEADER: Final = "content-length"
CACHE_CONTROL_HEADER: Final = "cache-control"
NO_STORE: Final = "no-store"
EMPTY_BODY: Final = b""
STATE_SCOPE_KEY: Final = "state"
SAFE_REQUEST_ID: Final = re.compile(FieldLimits.REQUEST_ID_PATTERN)
HOST_HEADER: Final = "host"
SERVER_HEADER: Final = "server"
INVALID_HOST_MESSAGE_KEY: Final = "validation.invalid_host"
HOST_PORT_SEPARATOR: Final = ":"
IPV6_CLOSE_BRACKET: Final = "]"
SUBDOMAIN_WILDCARD: Final = "*."
HSTS_MAX_AGE_SECONDS: Final = 31_536_000
DOCS_PATHS: Final = frozenset({DOCS_URL, OPENAPI_URL})
"""Documentation routes: Swagger loads scripts and styles the strict CSP blocks."""
API_CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
HSTS_VALUE: Final = f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains"
FIXED_SECURITY_HEADERS: Final[Mapping[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    ),
    "Cross-Origin-Resource-Policy": "same-site",
}


@final
class RequestIdMiddleware:
    """Gives every request a correlation id and echoes it in ``X-Request-ID``.

    A client supplied id is kept only if it is a valid UUID (``REQUEST_ID_PATTERN``,
    Seguridad 11.2); otherwise a new UUID4 replaces it. The id is
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

    ``path_limits`` gives a route its own limit by exact path, above or below the
    general one (offline batches and CGM files, API.md section 5).

    The declared ``Content-Length`` is checked before the app runs. Bodies sent
    without it (chunked) are counted while they are read: past the limit, any
    response the app tries to send is dropped and the 413 is sent instead,
    unless the app had already started its response.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        responses: ErrorResponseFactory,
        max_body_bytes: int,
        path_limits: Mapping[str, int] | None = None,
    ) -> None:
        self._app = app
        self._responses = responses
        self._max_body_bytes = max_body_bytes
        self._path_limits = dict(path_limits or {})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE:
            await self._app(scope, receive, send)
            return
        limit = self._path_limits.get(str(scope.get("path", "")), self._max_body_bytes)
        if self._declared_size_exceeds_limit(scope, limit):
            await self._reject(scope, receive, send, limit)
            return

        received_bytes = 0
        body_too_large = False
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes, body_too_large
            message = await receive()
            if message["type"] == HTTP_REQUEST_MESSAGE:
                received_bytes += len(message.get("body", EMPTY_BODY))
                if received_bytes > limit:
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
            await self._reject(scope, receive, send, limit)

    @staticmethod
    def _declared_size_exceeds_limit(scope: Scope, limit: int) -> bool:
        declared = Headers(scope=scope).get(CONTENT_LENGTH_HEADER)
        return declared is not None and declared.isdigit() and int(declared) > limit

    async def _reject(
        self, scope: Scope, receive: Receive, send: Send, limit: int
    ) -> None:
        response = self._responses.create(
            ErrorCode.PAYLOAD_TOO_LARGE, detail={"max_bytes": limit}
        )
        await response(scope, receive, send)


@final
class NoStoreCacheMiddleware:
    """Sends ``Cache-Control: no-store`` on every ``/api/v1`` response.

    A route that sets its own ``Cache-Control`` (``GET /meta/field-limits``) keeps
    it. Tokens, secrets and recovery codes therefore never land in a cache.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE or not str(scope.get("path", "")).startswith(
            API_V1_PREFIX
        ):
            await self._app(scope, receive, send)
            return

        async def send_with_cache_policy(message: Message) -> None:
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                headers = MutableHeaders(scope=message)
                if CACHE_CONTROL_HEADER not in headers:
                    headers[CACHE_CONTROL_HEADER] = NO_STORE
            await send(message)

        await self._app(scope, receive, send_with_cache_policy)


@final
class TrustedHostMiddleware:
    """Rejects a ``Host`` outside ``ALLOWED_HOSTS`` with the canonical error format.

    Starlette's own middleware answers in plain text. The code is
    ``400 VALIDATION_ERROR`` (the policy fixes none; open decision). Entries are
    exact hosts or ``*.example.test``, which matches any subdomain but not the
    bare domain. The port is ignored and the comparison is case insensitive.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        responses: ErrorResponseFactory,
        allowed_hosts: Iterable[str],
    ) -> None:
        self._app = app
        self._responses = responses
        self._allowed_hosts = tuple(host.lower() for host in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE or self._is_allowed(
            Headers(scope=scope).get(HOST_HEADER, "")
        ):
            await self._app(scope, receive, send)
            return
        response = self._responses.create(
            ErrorCode.VALIDATION_ERROR, message_key=INVALID_HOST_MESSAGE_KEY
        )
        response.status_code = HTTPStatus.BAD_REQUEST
        await response(scope, receive, send)

    def _is_allowed(self, host_header: str) -> bool:
        host = self._hostname(host_header)
        return any(
            host == allowed
            or (
                allowed.startswith(SUBDOMAIN_WILDCARD)
                and host.endswith(allowed[1:])
                and len(host) > len(allowed) - 1
            )
            for allowed in self._allowed_hosts
        )

    @staticmethod
    def _hostname(host_header: str) -> str:
        host = host_header.strip().lower()
        if host.startswith("["):
            return host[: host.find(IPV6_CLOSE_BRACKET) + 1]
        return host.partition(HOST_PORT_SEPARATOR)[0]


@final
class SecurityHeadersMiddleware:
    """Adds the security headers of Seguridad 13.1 to every HTTP response.

    A route that needs another value sets it itself: ``setdefault`` never
    overwrites. HSTS is sent only in production, where TLS ends before the app.
    ``Swagger`` routes get no CSP, because the strict one blocks its scripts
    (relaxed policy pending). ``Server`` is removed.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self._app = app
        self._hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != HTTP_SCOPE:
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == HTTP_RESPONSE_START_MESSAGE:
                headers = MutableHeaders(scope=message)
                for name, value in FIXED_SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if self._hsts:
                    headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
                if path not in DOCS_PATHS:
                    headers.setdefault(
                        "Content-Security-Policy", API_CONTENT_SECURITY_POLICY
                    )
                if SERVER_HEADER in headers:
                    del headers[SERVER_HEADER]
            await send(message)

        await self._app(scope, receive, send_with_headers)
