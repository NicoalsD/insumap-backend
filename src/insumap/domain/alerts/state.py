"""The life of an alert (P18 State): OPEN, ESCALATED, ACKNOWLEDGED and RESOLVED.

``OPEN`` or ``ESCALATED`` can be acknowledged; acknowledging stops the escalation
chain. Only an acknowledged alert can be resolved. ``RESOLVED`` is terminal. The
persisted value is the ``AlertStatus``; the behaviour lives in each state class,
and ``AlertState.from_status`` is the only ``match`` over the statuses.
"""

from __future__ import annotations

from abc import ABC
from enum import StrEnum
from typing import ClassVar, assert_never, final, override

from insumap.domain.identity.errors import InvalidStateTransitionError

MACHINE_NAME = "alert"


class AlertStatus(StrEnum):
    """Stored status of an alert (``alerts.alerts.status``)."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class AlertState(ABC):
    """Base of the alert machine. Every action not overridden is refused.

    Pattern: P18 State
    """

    status: ClassVar[AlertStatus]

    def acknowledge(self) -> AlertState:
        """Someone takes the alert over: the escalation stops."""
        raise self._invalid("acknowledge")

    def escalate(self) -> AlertState:
        """The escalation chain moves to the next level."""
        raise self._invalid("escalate")

    def resolve(self) -> AlertState:
        """The alert is closed with a note."""
        raise self._invalid("resolve")

    def _invalid(self, action: str) -> InvalidStateTransitionError:
        return InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)

    @staticmethod
    def from_status(status: AlertStatus) -> AlertState:
        """The state object of a stored status."""
        match status:
            case AlertStatus.OPEN:
                return OpenAlertState()
            case AlertStatus.ESCALATED:
                return EscalatedAlertState()
            case AlertStatus.ACKNOWLEDGED:
                return AcknowledgedAlertState()
            case AlertStatus.RESOLVED:
                return ResolvedAlertState()
            case _:
                assert_never(status)


@final
class OpenAlertState(AlertState):
    status = AlertStatus.OPEN

    @override
    def acknowledge(self) -> AlertState:
        return AcknowledgedAlertState()

    @override
    def escalate(self) -> AlertState:
        return EscalatedAlertState()


@final
class EscalatedAlertState(AlertState):
    status = AlertStatus.ESCALATED

    @override
    def acknowledge(self) -> AlertState:
        return AcknowledgedAlertState()

    @override
    def escalate(self) -> AlertState:
        return EscalatedAlertState()


@final
class AcknowledgedAlertState(AlertState):
    status = AlertStatus.ACKNOWLEDGED

    @override
    def resolve(self) -> AlertState:
        return ResolvedAlertState()


@final
class ResolvedAlertState(AlertState):
    status = AlertStatus.RESOLVED
