"""Correlation id of the request being processed.

The api middleware binds it and the logging setup reads it, so every log line
written while serving a request carries the same ``request_id``. It lives in
``contextvars``, so concurrent requests never see each other's id.
"""

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    """Return the id of the request being processed, if any."""
    return _request_id.get()


def bind_request_id(request_id: str) -> Token[str | None]:
    """Make ``request_id`` the current id; keep the token to unbind it."""
    return _request_id.set(request_id)


def unbind_request_id(token: Token[str | None]) -> None:
    """Restore the id that was current before ``bind_request_id``."""
    _request_id.reset(token)
