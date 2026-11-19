from datetime import UTC, datetime
from typing import override
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.commands.base import CommandHandler
from insumap.application.commands.transactional import (
    CurrentUnitOfWork,
    TransactionalCommandHandler,
)
from insumap.domain.common.events import DomainEvent
from insumap.domain.identity.roles import Role
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
from tests.support.identity_fakes import FakeUnitOfWorkPort

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def command() -> RenameThingCommand:
    return RenameThingCommand(actor=clinic_admin(), new_name="Sede norte")


class EventfulHandler(CommandHandler[RenameThingCommand, UUID]):
    def __init__(self, current: CurrentUnitOfWork) -> None:
        self._current = current

    @override
    def handle(self, command: RenameThingCommand) -> UUID:
        self._current.collect([DomainEvent(event_id=ENTITY_ID, occurred_at=NOW)])
        return ENTITY_ID


def test_runs_the_handler_in_the_context_of_the_actor_and_commits_once() -> None:
    uow = FakeUnitOfWorkPort()
    handler = TransactionalCommandHandler(
        RenameThingHandler(), uow, CurrentUnitOfWork()
    )

    assert handler.handle(command()) == ENTITY_ID

    [context] = uow.contexts[:1]
    assert (context.user_id, context.clinic_id, context.role) == (
        ADMIN_ID,
        CLINIC_ID,
        Role.CLINIC_ADMIN,
    )
    assert uow.commits == 1


def test_audit_row_and_action_share_the_transaction() -> None:
    uow, log = FakeUnitOfWorkPort(), InMemoryAuditLog()
    inner = AuditingCommandHandler(RenameThingHandler(), log, FixedClock(NOW))

    TransactionalCommandHandler(inner, uow, CurrentUnitOfWork()).handle(command())

    assert uow.commits == 1
    assert len(log.entries) == 1


def test_a_failing_action_does_not_commit() -> None:
    uow = FakeUnitOfWorkPort()
    handler = TransactionalCommandHandler(FailingHandler(), uow, CurrentUnitOfWork())

    with pytest.raises(RuntimeError):
        handler.handle(command())

    assert uow.commits == 0


def test_events_are_published_only_after_the_commit() -> None:
    uow, current = FakeUnitOfWorkPort(), CurrentUnitOfWork()

    TransactionalCommandHandler(EventfulHandler(current), uow, current).handle(
        command()
    )

    assert [event.event_id for event in uow.published] == [ENTITY_ID]


def test_collecting_outside_a_command_is_a_programming_error() -> None:
    with pytest.raises(RuntimeError, match="no command is running"):
        CurrentUnitOfWork().collect([])
