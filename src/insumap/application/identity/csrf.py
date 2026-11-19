"""CSRF defence of the endpoints that use the refresh cookie."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final, final

from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.domain.identity.errors import PermissionDeniedError

REQUIRED_REQUESTED_WITH: Final = "insumap-web"
CROSS_SITE: Final = "cross-site"


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshRequestOrigin:
    """The three headers the check reads."""

    requested_with: str | None
    origin: str | None
    sec_fetch_site: str | None


@final
class RefreshRequestGuard:
    """``X-Requested-With: insumap-web`` is mandatory; ``Origin`` must be allowed.

    A request that fails answers ``403 FORBIDDEN`` and leaves a
    ``CSRF_CHECK_FAILED`` event, committed on its own so the answer does not
    undo it. ``Origin: null`` is never accepted.
    """

    def __init__(
        self,
        *,
        allowed_origins: Collection[str],
        uow: UnitOfWorkPort,
        events: SecurityEventPort,
    ) -> None:
        self._allowed = frozenset(allowed_origins)
        self._uow = uow
        self._events = events

    def ensure_allowed(self, request: RefreshRequestOrigin) -> None:
        """Raise ``PermissionDeniedError`` unless the request looks same-site."""
        if (
            request.requested_with == REQUIRED_REQUESTED_WITH
            and (request.origin is None or request.origin in self._allowed)
            and request.sec_fetch_site != CROSS_SITE
        ):
            return
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            self._events.record(
                SecurityEvent(event_type=SecurityEventType.CSRF_CHECK_FAILED)
            )
            uow.commit()
        raise PermissionDeniedError
