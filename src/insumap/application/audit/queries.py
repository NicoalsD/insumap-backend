"""``GET /audit-log``, ``GET /audit-log/data-access`` and ``GET /security-events``.

Each read runs in its own transaction under the caller's row level security. The
clinic always comes from the token, never from the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.audit.ports import (
    AuditLogFilter,
    AuditLogReadPort,
    AuditLogRow,
    DataAccessFilter,
    DataAccessReadPort,
    DataAccessRow,
    SecurityEventFilter,
    SecurityEventKind,
    SecurityEventReadPort,
    SecurityEventRow,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.security.events import SecuritySeverity
from insumap.application.users.access import clinic_of
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ListAuditLogInput:
    """The caller, the optional filters and the page asked for."""

    actor: Actor
    filters: AuditLogFilter
    page: PageRequest


@final
class ListAuditLogUseCase:
    """A page of the actions of the caller's clinic: names of fields, never values."""

    def __init__(self, *, uow: UnitOfWorkPort, reader: AuditLogReadPort) -> None:
        self._uow = uow
        self._reader = reader

    def execute(self, input: ListAuditLogInput) -> Page[AuditLogRow]:
        """Only ``audit.read``; the clinic comes from the token."""
        input.actor.require(PermissionCode.AUDIT_READ)
        clinic_id = clinic_of(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._reader.list(clinic_id, input.filters, input.page)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListDataAccessInput:
    """The caller, the optional filters and the page asked for."""

    actor: Actor
    filters: DataAccessFilter
    page: PageRequest


@final
class ListDataAccessUseCase:
    """A page of the reads of clinical data in the caller's clinic.

    This listing is not itself a clinical read, so it is not audited (P09).
    """

    def __init__(self, *, uow: UnitOfWorkPort, reader: DataAccessReadPort) -> None:
        self._uow = uow
        self._reader = reader

    def execute(self, input: ListDataAccessInput) -> Page[DataAccessRow]:
        """Only ``audit.read``; the clinic comes from the token."""
        input.actor.require(PermissionCode.AUDIT_READ)
        clinic_id = clinic_of(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._reader.list(clinic_id, input.filters, input.page)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListSecurityEventsInput:
    """The caller, the optional filters and the page asked for."""

    actor: Actor
    event_type: SecurityEventKind | None = None
    severity: SecuritySeverity | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    page: PageRequest


@final
class ListSecurityEventsUseCase:
    """Security events: a clinic's own with ``audit.read``, the platform's with
    ``audit.read_platform`` (a caller without a clinic)."""

    def __init__(self, *, uow: UnitOfWorkPort, reader: SecurityEventReadPort) -> None:
        self._uow = uow
        self._reader = reader

    def execute(self, input: ListSecurityEventsInput) -> Page[SecurityEventRow]:
        """The scope is decided from the token before any row is read."""
        clinic_id = security_scope(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._reader.list(
                SecurityEventFilter(
                    clinic_id=clinic_id,
                    event_type=input.event_type,
                    severity=input.severity,
                    occurred_from=input.occurred_from,
                    occurred_to=input.occurred_to,
                ),
                input.page,
            )


def security_scope(actor: Actor) -> UUID | None:
    """``None`` for the platform (``audit.read_platform``), the clinic otherwise.

    A caller with a clinic needs ``audit.read`` and sees only that clinic. A caller
    without a clinic needs ``audit.read_platform`` and sees every event.
    """
    if actor.clinic_id is None:
        if PermissionCode.AUDIT_READ_PLATFORM not in actor.permissions:
            raise PermissionDeniedError
        return None
    if PermissionCode.AUDIT_READ not in actor.permissions:
        raise PermissionDeniedError
    return actor.clinic_id
