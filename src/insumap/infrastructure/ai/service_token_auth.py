"""The service token as an ``httpx.Auth``, so it never sits in a URL or a log."""

from __future__ import annotations

from collections.abc import Generator
from typing import final, override

import httpx
from pydantic import SecretStr


@final
class ServiceTokenAuth(httpx.Auth):
    """Adds ``Authorization: Bearer <token>`` to every request of the client."""

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    @override
    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response]:
        request.headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        yield request

    def __repr__(self) -> str:
        return "ServiceTokenAuth(token=***)"
