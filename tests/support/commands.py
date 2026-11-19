"""Doubles and sample commands shared by the command infrastructure tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override
from uuid import UUID

from insumap.application.commands.auditing import AuditEntry, AuditLogPort
from insumap.application.commands.base import (
    AuditSubject,
    Command,
    CommandHandler,
)
from insumap.application.common.actor import Actor
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role

CLINIC_ID = UUID(int=10)
ADMIN_ID = UUID(int=11)
ENTITY_ID = UUID(int=99)


def clinic_admin(*permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=ADMIN_ID,
        clinic_id=CLINIC_ID,
        role=Role.CLINIC_ADMIN,
        permissions=frozenset(permissions),
        requires_mfa=True,
        mfa_verified=True,
    )


class InMemoryAuditLog(AuditLogPort):
    """Keeps the entries; ``fail`` makes the write raise, like a broken database."""

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []
        self.fail = False

    @override
    def record(self, entry: AuditEntry) -> None:
        if self.fail:
            raise RuntimeError("audit write failed")
        self.entries.append(entry)


@dataclass(frozen=True, slots=True, kw_only=True)
class RenameThingCommand(Command[UUID]):
    audit_action = "THING_RENAMED"
    audit_entity_type = "THING"

    new_name: str

    @override
    def audit_subject(self, result: UUID) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result,
            changed_fields=("name",),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class OtherCommand(Command[None]):
    audit_action = "OTHER_DONE"
    audit_entity_type = "THING"


class RenameThingHandler(CommandHandler[RenameThingCommand, UUID]):
    def __init__(self) -> None:
        self.calls: list[RenameThingCommand] = []

    @override
    def handle(self, command: RenameThingCommand) -> UUID:
        self.calls.append(command)
        return ENTITY_ID


class FailingHandler(CommandHandler[RenameThingCommand, UUID]):
    @override
    def handle(self, command: RenameThingCommand) -> UUID:
        raise RuntimeError("the action failed")
