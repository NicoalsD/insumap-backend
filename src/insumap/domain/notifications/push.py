"""A Web Push endpoint the browser sent: untrusted data checked before storing.

Only https, a public host from the allowlist and no IP literal (Seguridad.md
13.4). The endpoint never reaches a log: it is a bearer of the subscription.
"""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, final
from urllib.parse import urlsplit

from insumap.domain.notifications.errors import PushEndpointRejectedError
from insumap.shared.field_limits import FieldLimits

HTTPS: Final = "https"
WILDCARD_PREFIX: Final = "*."


@final
@dataclass(frozen=True, slots=True)
class PushEndpoint:
    """An endpoint that passed every check; ``endpoint_hash`` is its SHA-256."""

    url: str
    host: str

    @classmethod
    def parse(cls, raw: str, *, allowed_hosts: Iterable[str]) -> PushEndpoint:
        """The endpoint, or ``PushEndpointRejectedError`` with no detail to echo."""
        parts = urlsplit(raw)
        host = parts.hostname or ""
        if (
            len(raw) > FieldLimits.PUSH_ENDPOINT_MAX_LENGTH
            or parts.scheme != HTTPS
            or not host
            or parts.username is not None
            or parts.password is not None
            or _is_ip_literal(host)
            or not any(_matches(host, allowed) for allowed in allowed_hosts)
        ):
            raise PushEndpointRejectedError
        return cls(url=raw, host=host)

    @property
    def endpoint_hash(self) -> str:
        """SHA-256 of the URL: the unique key of ``alerts.push_subscriptions``."""
        return hashlib.sha256(self.url.encode()).hexdigest()


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _matches(host: str, allowed: str) -> bool:
    """``fcm.example`` matches itself; ``*.example`` matches its subdomains only."""
    pattern = allowed.strip().lower()
    if pattern.startswith(WILDCARD_PREFIX):
        return host.endswith("." + pattern[len(WILDCARD_PREFIX) :])
    return host == pattern
