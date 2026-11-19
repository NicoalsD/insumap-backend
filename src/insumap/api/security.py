"""Security of the HTTP surface: bearer scheme, actor dependency, refresh cookie."""

from datetime import datetime
from typing import Annotated, Final, final

from fastapi import Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from insumap.application.common.actor import Actor
from insumap.application.identity.authenticate import (
    AuthenticateActorUseCase,
    SessionScope,
)
from insumap.application.identity.csrf import RefreshRequestGuard, RefreshRequestOrigin
from insumap.domain.identity.errors import UnauthenticatedError
from insumap.shared.field_limits import FieldLimits

BEARER_SCHEME_NAME: Final = "bearerAuth"
BEARER_FORMAT: Final = "JWT"
AUTHORIZATION_HEADER: Final = "authorization"
REFRESH_COOKIE_NAME: Final = "__Secure-insumap_rt"
REFRESH_COOKIE_PATH: Final = "/api/v1/auth"
REQUESTED_WITH_HEADER: Final = "x-requested-with"
ORIGIN_HEADER: Final = "origin"
SEC_FETCH_SITE_HEADER: Final = "sec-fetch-site"
UNKNOWN_CLIENT: Final = "unknown"

bearer_auth: Final = HTTPBearer(
    scheme_name=BEARER_SCHEME_NAME,
    bearerFormat=BEARER_FORMAT,
    auto_error=False,
    description=(
        "Access token JWT de corta duración. Se envía en el encabezado "
        "`Authorization: Bearer <token>`."
    ),
)
"""Bearer JWT scheme. ``auto_error=False`` leaves the 401 to the canonical
error format instead of FastAPI's default answer."""

type Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_auth)]


def client_ip(request: Request) -> str:
    """The address of the peer, the subject of the IP rate limits."""
    return request.client.host if request.client else UNKNOWN_CLIENT


@final
class ActorGuard:
    """FastAPI dependency: the bearer token becomes the ``Actor`` of the request.

    Deny by default: no token, an oversized header or any invalid token is the
    same ``401``; ``scope`` decides which sessions the route accepts.
    """

    def __init__(
        self, authenticate: AuthenticateActorUseCase, scope: SessionScope
    ) -> None:
        self._authenticate = authenticate
        self._scope = scope

    def __call__(self, request: Request, credentials: Credentials) -> Actor:
        header = request.headers.get(AUTHORIZATION_HEADER, "")
        if (
            credentials is None
            or len(header.encode()) > FieldLimits.AUTH_HEADER_MAX_BYTES
        ):
            raise UnauthenticatedError
        return self._authenticate.execute(credentials.credentials, self._scope)


@final
class RefreshCsrfGuard:
    """FastAPI dependency: CSRF check of the endpoints that use the cookie."""

    def __init__(self, guard: RefreshRequestGuard) -> None:
        self._guard = guard

    def __call__(self, request: Request) -> None:
        self._guard.ensure_allowed(
            RefreshRequestOrigin(
                requested_with=request.headers.get(REQUESTED_WITH_HEADER),
                origin=request.headers.get(ORIGIN_HEADER),
                sec_fetch_site=request.headers.get(SEC_FETCH_SITE_HEADER),
            )
        )


@final
class RefreshCookie:
    """Builds and clears the refresh cookie; its attributes are not negotiable.

    ``__Secure-`` makes the browser require ``Secure``; the cookie has no
    ``Domain`` and only travels to the authentication endpoints.
    """

    def set(
        self, response: Response, *, token: str, expires_at: datetime, now: datetime
    ) -> None:
        """Set the cookie with the remaining life of the token."""
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=token,
            max_age=max(int((expires_at - now).total_seconds()), 0),
            path=REFRESH_COOKIE_PATH,
            secure=True,
            httponly=True,
            samesite="strict",
        )

    def clear(self, response: Response) -> None:
        """Tell the browser to drop the cookie."""
        response.delete_cookie(
            key=REFRESH_COOKIE_NAME,
            path=REFRESH_COOKIE_PATH,
            secure=True,
            httponly=True,
            samesite="strict",
        )
