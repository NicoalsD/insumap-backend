"""Pattern: P13 Command. The bus routes a command to the handler of its type."""

import pytest

from insumap.application.commands.base import (
    CommandNotHandledError,
    InMemoryCommandBus,
    bind,
)
from tests.support.commands import (
    ENTITY_ID,
    OtherCommand,
    RenameThingCommand,
    RenameThingHandler,
    clinic_admin,
)


def test_dispatches_to_the_handler_of_the_command_type_and_returns_its_result() -> None:
    handler = RenameThingHandler()
    bus = InMemoryCommandBus([bind(RenameThingCommand, handler)])
    command = RenameThingCommand(actor=clinic_admin(), new_name="Sede norte")

    result = bus.dispatch(command)

    assert result == ENTITY_ID
    assert handler.calls == [command]


def test_a_command_without_a_handler_is_a_wiring_error() -> None:
    bus = InMemoryCommandBus([bind(RenameThingCommand, RenameThingHandler())])

    with pytest.raises(CommandNotHandledError, match="OtherCommand"):
        bus.dispatch(OtherCommand(actor=clinic_admin()))


def test_building_the_bus_fails_when_a_required_command_has_no_handler() -> None:
    with pytest.raises(CommandNotHandledError, match="OtherCommand"):
        InMemoryCommandBus(
            [bind(RenameThingCommand, RenameThingHandler())],
            required=[RenameThingCommand, OtherCommand],
        )


def test_commands_are_immutable_and_carry_their_actor() -> None:
    command = RenameThingCommand(actor=clinic_admin(), new_name="Sede norte")

    with pytest.raises(AttributeError):
        command.new_name = "otra"  # type: ignore[misc]
    assert command.actor.user_id
