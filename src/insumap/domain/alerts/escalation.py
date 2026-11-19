"""The escalation chain of an alert (P12): who is told when nobody acknowledges.

The chain orders the recipients: the patient (level 0, told when the alert opens),
the primary doctor, the care team and the clinic administrator. A rule's
``escalation`` lists the steps after the opening, one per level, each with its wait.
The chain itself does not read the database: the caller passes the recipients in
an ``EscalationContext``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

LEVEL: Final = "level"
RECIPIENT: Final = "recipient"
WAIT_MINUTES: Final = "wait_minutes"


class EscalationRecipient(StrEnum):
    """Who the chain reaches, in order: the position is the level."""

    PATIENT = "PATIENT"
    PRIMARY_DOCTOR = "PRIMARY_DOCTOR"
    CARE_TEAM = "CARE_TEAM"
    CLINIC_ADMIN = "CLINIC_ADMIN"


LEVEL_BY_RECIPIENT: Final[Mapping[EscalationRecipient, int]] = {
    recipient: position for position, recipient in enumerate(EscalationRecipient)
}


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class EscalationStep:
    """One step after the opening: the level, who is told and the wait before it."""

    level: int
    recipient: EscalationRecipient
    wait: timedelta

    def to_definition(self) -> dict[str, object]:
        """The jsonb element stored in ``alerts.alert_rules.escalation``."""
        return {
            LEVEL: self.level,
            RECIPIENT: self.recipient.value,
            WAIT_MINUTES: int(self.wait.total_seconds() // 60),
        }


def parse_escalation(raw: Sequence[Mapping[str, object]]) -> tuple[EscalationStep, ...]:
    """Steps 1, 2, 3... in order; each recipient matches its level, waits are bounded.

    The steps must be consecutive from level 1: a chain with a gap has no meaning.
    """
    if len(raw) > FieldLimits.ALERT_LEVEL_MAX:
        raise _invalid("too_many_steps")
    steps = tuple(_step(item) for item in raw)
    for position, step in enumerate(steps, start=FieldLimits.ALERT_LEVEL_MIN):
        if step.level != position:
            raise _invalid("levels_not_consecutive")
    return steps


def _step(raw: Mapping[str, object]) -> EscalationStep:
    level = raw.get(LEVEL)
    if (
        isinstance(level, bool)
        or not isinstance(level, int)
        or not FieldLimits.ALERT_LEVEL_MIN <= level <= FieldLimits.ALERT_LEVEL_MAX
    ):
        raise _invalid("invalid_level")
    try:
        recipient = EscalationRecipient(str(raw.get(RECIPIENT)))
    except ValueError:
        raise _invalid("invalid_recipient") from None
    if LEVEL_BY_RECIPIENT[recipient] != level:
        raise _invalid("recipient_level_mismatch")
    wait = raw.get(WAIT_MINUTES)
    if (
        isinstance(wait, bool)
        or not isinstance(wait, int)
        or not FieldLimits.ALERT_MINUTES_MIN <= wait <= FieldLimits.ALERT_MINUTES_MAX
    ):
        raise _invalid("invalid_wait_minutes")
    return EscalationStep(
        level=level, recipient=recipient, wait=timedelta(minutes=wait)
    )


def _invalid(issue: str) -> InsumapError:
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"field": "body.escalation", "type": issue}]},
    )


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class EscalationContext:
    """Who the chain can reach for one alert, read by the caller."""

    patient_user_id: UUID | None
    primary_doctor_id: UUID | None
    team_doctor_ids: tuple[UUID, ...]
    clinic_admin_ids: tuple[UUID, ...]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class EscalationOutcome:
    """The level that answered and the people it reaches."""

    level: int
    recipients: tuple[UUID, ...]


class AlertEscalationHandler(ABC):
    """One link of the chain: it answers its own level or passes the request on.

    Pattern: P12 Chain of Responsibility
    """

    level: ClassVar[int]

    def __init__(self) -> None:
        self._next: AlertEscalationHandler | None = None

    def set_next(self, handler: AlertEscalationHandler) -> AlertEscalationHandler:
        """Link ``handler`` after this one and return it, so links can be chained."""
        self._next = handler
        return handler

    def escalate(
        self, ctx: EscalationContext, *, from_level: int
    ) -> EscalationOutcome | None:
        """The first link at or after ``from_level`` that has someone to reach.

        A level with nobody to reach passes to the next one. ``None`` means the
        chain has nobody left to tell.
        """
        if self.level >= from_level:
            recipients = self.recipients(ctx)
            if recipients:
                return EscalationOutcome(level=self.level, recipients=recipients)
        if self._next is None:
            return None
        return self._next.escalate(ctx, from_level=from_level)

    @abstractmethod
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]:
        """Who this link reaches; empty when there is nobody."""


@final
class PatientEscalationHandler(AlertEscalationHandler):
    level = LEVEL_BY_RECIPIENT[EscalationRecipient.PATIENT]

    @override
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]:
        return (ctx.patient_user_id,) if ctx.patient_user_id else ()


@final
class PrimaryDoctorEscalationHandler(AlertEscalationHandler):
    level = LEVEL_BY_RECIPIENT[EscalationRecipient.PRIMARY_DOCTOR]

    @override
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]:
        return (ctx.primary_doctor_id,) if ctx.primary_doctor_id else ()


@final
class CareTeamEscalationHandler(AlertEscalationHandler):
    level = LEVEL_BY_RECIPIENT[EscalationRecipient.CARE_TEAM]

    @override
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]:
        return ctx.team_doctor_ids


@final
class ClinicAdminEscalationHandler(AlertEscalationHandler):
    level = LEVEL_BY_RECIPIENT[EscalationRecipient.CLINIC_ADMIN]

    @override
    def recipients(self, ctx: EscalationContext) -> tuple[UUID, ...]:
        return ctx.clinic_admin_ids


def build_escalation_chain() -> AlertEscalationHandler:
    """The chain in level order; each link is linked here, never inside another."""
    head = PatientEscalationHandler()
    head.set_next(PrimaryDoctorEscalationHandler()).set_next(
        CareTeamEscalationHandler()
    ).set_next(ClinicAdminEscalationHandler())
    return head
