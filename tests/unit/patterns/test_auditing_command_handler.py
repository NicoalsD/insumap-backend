"""Pattern: P09 Decorator. The audit row of a command, written with the action."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import InMemoryCommandBus, bind
from insumap.domain.identity.roles import Role
from insumap.shared.request_context import bind_request_id, unbind_request_id
from tests.support.commands import (
    ADMIN_ID,
    CLINIC_ID,
    ENTITY_ID,
    FailingHandler,
    InMemoryAuditLog,
    RenameThingCommand,
    RenameThingHandler,
    clinic_admin,
)
from tests.support.fixed_clock import FixedClock

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def command() -> RenameThingCommand:
    return RenameThingCommand(actor=clinic_admin(), new_name="Sede norte")


def test_a_successful_command_leaves_one_row_and_returns_the_result() -> None:
    log = InMemoryAuditLog()
    inner = RenameThingHandler()
    handler = AuditingCommandHandler(inner, log, FixedClock(NOW))
    token = bind_request_id("req-1")
    try:
        result = handler.handle(command())
    finally:
        unbind_request_id(token)

    assert result == ENTITY_ID
    assert len(inner.calls) == 1
    [entry] = log.entries
    assert entry.action == "THING_RENAMED"
    assert entry.entity_type == "THING"
    assert entry.entity_id == ENTITY_ID
    assert entry.clinic_id == CLINIC_ID
    assert entry.actor_user_id == ADMIN_ID
    assert entry.actor_role is Role.CLINIC_ADMIN
    assert entry.changed_fields == ("name",)
    assert entry.occurred_at == NOW
    assert entry.request_id == "req-1"


def test_the_row_never_holds_the_values_of_the_command() -> None:
    log = InMemoryAuditLog()
    AuditingCommandHandler(RenameThingHandler(), log, FixedClock(NOW)).handle(command())

    assert "Sede norte" not in repr(log.entries)


def test_a_failed_command_leaves_no_row_and_the_error_propagates() -> None:
    log = InMemoryAuditLog()
    handler = AuditingCommandHandler(FailingHandler(), log, FixedClock(NOW))

    with pytest.raises(RuntimeError, match="the action failed"):
        handler.handle(command())

    assert log.entries == []


def test_a_failed_audit_write_fails_the_command() -> None:
    log = InMemoryAuditLog()
    log.fail = True
    handler = AuditingCommandHandler(RenameThingHandler(), log, FixedClock(NOW))

    with pytest.raises(RuntimeError, match="audit write failed"):
        handler.handle(command())


def test_the_decorated_handler_is_registered_in_the_bus() -> None:
    log = InMemoryAuditLog()
    bus = InMemoryCommandBus(
        [
            bind(
                RenameThingCommand,
                AuditingCommandHandler(RenameThingHandler(), log, FixedClock(NOW)),
            )
        ]
    )

    assert bus.dispatch(command()) == ENTITY_ID
    assert [entry.entity_id for entry in log.entries] == [UUID(int=99)]
