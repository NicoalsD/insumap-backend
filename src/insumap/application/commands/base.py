"""Commands, handlers and the bus that routes them (P13).

A command is an immutable decision that carries its actor. The bus only
routes: authorization lives in the handler, auditing in ``AuditingCommandHandler``
and the transaction in ``TransactionalCommandHandler``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import ClassVar, Never, cast, final, override
from uuid import UUID

from insumap.application.common.actor import Actor


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditSubject:
    """What the audit log keeps of a command: identifiers and field names only.

    Never values: no clinical data, names, secrets or request bodies.
    """

    clinic_id: UUID | None
    entity_id: UUID | None = None
    reason: str | None = None
    changed_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Command[R]:
    """Base of every decision. ``R`` is the type its handler returns.

    ``audit_action`` (``UPPER_SNAKE``) and ``audit_entity_type`` name the audit
    row; ``audit_subject`` completes it from the command and its result.
    """

    actor: Actor

    audit_action: ClassVar[str]
    audit_entity_type: ClassVar[str]

    def audit_subject(self, result: R) -> AuditSubject:
        """The audit data of this command once it succeeded (default: the actor's)."""
        del result
        return AuditSubject(clinic_id=self.actor.clinic_id)


class CommandHandler[C: Command[Never], R](ABC):
    """Executes one kind of command."""

    @abstractmethod
    def handle(self, command: C) -> R:
        """Run the decision; raise an ``InsumapError`` when it is refused."""


type Registration = tuple[type[Command[Never]], CommandHandler[Command[Never], object]]


def bind[C: Command[Never], R](
    command_type: type[C], handler: CommandHandler[C, R]
) -> Registration:
    """Typed registration: the handler must accept exactly this command type.

    ``Command[Never]`` is the common supertype of every command (``R`` is only
    consumed by ``audit_subject``, so ``Command`` is contravariant in it). mypy
    cannot tie ``R`` to the ``R`` of ``Command[R]`` (PEP 695 bounds cannot
    mention another type parameter), so the result type is checked by the
    handler test, not by the registration.
    """
    return (
        cast("type[Command[Never]]", command_type),
        cast("CommandHandler[Command[Never], object]", handler),
    )


@final
class CommandNotHandledError(RuntimeError):
    """A command reached the bus with no handler: a wiring bug, not a user error."""


class CommandBus(ABC):
    """Routes a command to its handler."""

    @abstractmethod
    def dispatch[R](self, command: Command[R]) -> R:
        """Run ``command`` and return what its handler returns."""


@final
class InMemoryCommandBus(CommandBus):
    """Invoker of P13. It only routes; it does not authorize, audit or commit.

    Building the bus fails when a required command has no handler, so the gap
    shows at startup and not at the first request.

    Pattern: P13 Command
    """

    def __init__(
        self,
        registrations: Collection[Registration],
        *,
        required: Collection[type[Command[Never]]] = (),
    ) -> None:
        self._handlers: Mapping[
            type[Command[Never]], CommandHandler[Command[Never], object]
        ] = dict(registrations)
        missing = set(required) - set(self._handlers)
        if missing:
            names = ", ".join(sorted(command.__name__ for command in missing))
            raise CommandNotHandledError(f"commands without a handler: {names}")

    @override
    def dispatch[R](self, command: Command[R]) -> R:
        handler = self._handlers.get(type(command))
        if handler is None:
            raise CommandNotHandledError(type(command).__name__)
        return cast("R", handler.handle(command))
