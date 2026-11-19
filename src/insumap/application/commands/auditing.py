"""Audit of the commands (P09 Decorator): ``audit.audit_log`` rows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Never, cast, final, override
from uuid import UUID

from insumap.application.commands.base import Command, CommandHandler
from insumap.domain.identity.roles import Role
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEntry:
    """One row of ``audit.audit_log``: who did what to which entity, never values."""

    occurred_at: datetime
    clinic_id: UUID | None
    actor_user_id: UUID
    actor_role: Role
    action: str
    entity_type: str
    entity_id: UUID | None
    reason: str | None
    changed_fields: tuple[str, ...]
    request_id: str | None


class AuditLogPort(ABC):
    """Appends audit rows inside the transaction that is open."""

    @abstractmethod
    def record(self, entry: AuditEntry) -> None:
        """Append ``entry`` in the current transaction (fail closed)."""


@final
class AuditingCommandHandler[C: Command[Never], R](CommandHandler[C, R]):
    """Appends the audit row of a command that succeeded, then returns its result.

    It sits inside ``TransactionalCommandHandler``: the row is written in the
    same transaction as the action, so a failed action leaves no row and a
    failed audit write rolls the action back (``Seguridad.md``, 7.2).

    Pattern: P09 Decorator
    """

    def __init__(
        self, inner: CommandHandler[C, R], log: AuditLogPort, clock: Clock
    ) -> None:
        self._inner = inner
        self._log = log
        self._clock = clock

    @override
    def handle(self, command: C) -> R:
        result = self._inner.handle(command)
        subject = cast("Command[R]", command).audit_subject(result)
        self._log.record(
            AuditEntry(
                occurred_at=self._clock.now(),
                clinic_id=subject.clinic_id,
                actor_user_id=command.actor.user_id,
                actor_role=command.actor.role,
                action=command.audit_action,
                entity_type=command.audit_entity_type,
                entity_id=subject.entity_id,
                reason=subject.reason,
                changed_fields=subject.changed_fields,
                request_id=current_request_id(),
            )
        )
        return result
