"""Transaction boundary of a command: one unit of work around handler and audit."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Never, final, override

from insumap.application.commands.base import Command, CommandHandler
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWork,
    UnitOfWorkPort,
)
from insumap.domain.common.events import DomainEvent


@final
class CurrentUnitOfWork:
    """The unit of work a command runs in, so a handler can collect its events.

    Events leave only after the commit that ``TransactionalCommandHandler``
    makes once handler and audit succeeded (P17).
    """

    def __init__(self) -> None:
        self._current: ContextVar[UnitOfWork | None] = ContextVar(
            "insumap_current_unit_of_work", default=None
        )

    def collect(self, events: Sequence[DomainEvent]) -> None:
        """Keep ``events`` to publish after the commit."""
        unit = self._current.get()
        if unit is None:
            raise RuntimeError("no command is running")
        unit.collect(events)

    @contextmanager
    def bind(self, unit: UnitOfWork) -> Iterator[None]:
        """Make ``unit`` the current one for the block."""
        token = self._current.set(unit)
        try:
            yield
        finally:
            self._current.reset(token)


@final
class TransactionalCommandHandler[C: Command[Never], R](CommandHandler[C, R]):
    """Opens the transaction with the RLS context of the actor and commits it.

    The handler and the audit decorator inside run in that transaction. An
    error rolls everything back: the action and its audit row.
    """

    def __init__(
        self,
        inner: CommandHandler[C, R],
        uow: UnitOfWorkPort,
        current: CurrentUnitOfWork,
    ) -> None:
        self._inner = inner
        self._uow = uow
        self._current = current

    @override
    def handle(self, command: C) -> R:
        with (
            self._uow.begin(TransactionContext.for_actor(command.actor)) as unit,
            self._current.bind(unit),
        ):
            result = self._inner.handle(command)
            unit.commit()
        return result
