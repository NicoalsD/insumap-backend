"""Decisions about follow-up controls: the doctor schedules and closes them (P13)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.application.follow_ups.ports import FollowUpRepositoryPort
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.common.reason import Reason
from insumap.domain.follow_ups.follow_up import FollowUp, FollowUpOutcome
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.i18n import MessageCatalog
from insumap.shared.time import Clock

FOLLOW_UP_ENTITY: Final = "FOLLOW_UP"
TITLE_KEY: Final = "follow_up.control_title"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateFollowUpCommand(Command[FollowUp]):
    """The doctor schedules a control for a patient he cares for."""

    audit_action: ClassVar[str] = "FOLLOW_UP_CREATED"
    audit_entity_type: ClassVar[str] = FOLLOW_UP_ENTITY

    patient_id: UUID
    scheduled_for: datetime

    @override
    def audit_subject(self, result: FollowUp) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.follow_up_id,
            changed_fields=("scheduled_for", "status"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CloseFollowUpCommand(Command[FollowUp]):
    """The doctor records how a control ended, with its result note."""

    audit_action: ClassVar[str] = "FOLLOW_UP_CLOSED"
    audit_entity_type: ClassVar[str] = FOLLOW_UP_ENTITY

    follow_up_id: UUID
    outcome: FollowUpOutcome
    result_note: str

    @override
    def audit_subject(self, result: FollowUp) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.follow_up_id,
            reason=result.result_note,
            changed_fields=("status", "result_note", "closed_at"),
        )


@final
class CreateFollowUpCommandHandler(CommandHandler[CreateFollowUpCommand, FollowUp]):
    """Schedules a control of an assigned patient; the date must be in the future.

    Pattern: P13 Command (handler)
    """

    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        follow_ups: FollowUpRepositoryPort,
        ids: IdGenerator,
        clock: Clock,
        catalog: MessageCatalog,
    ) -> None:
        self._gate = gate
        self._follow_ups = follow_ups
        self._ids = ids
        self._clock = clock
        self._catalog = catalog

    @override
    def handle(self, command: CreateFollowUpCommand) -> FollowUp:
        actor = command.actor
        patient_id = self._gate.enter(
            actor,
            PermissionCode.FOLLOW_UPS_MANAGE,
            command.patient_id,
            DataResource.TREATMENT_PLAN,
        )
        if actor.clinic_id is None:
            raise PermissionDeniedError
        follow_up = FollowUp.schedule(
            follow_up_id=self._ids.new_id(),
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            scheduled_for=command.scheduled_for,
            by=actor.user_id,
            title=self._catalog.render(TITLE_KEY),
            at=self._clock.now(),
        )
        self._follow_ups.insert(follow_up)
        return follow_up


@final
class CloseFollowUpCommandHandler(CommandHandler[CloseFollowUpCommand, FollowUp]):
    """Closes a scheduled control of an assigned patient, with its result note.

    A control of a patient who is not assigned, or of another clinic, is ``404``.
    A control already closed is ``409`` (``INVALID_STATE_TRANSITION``).
    """

    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        follow_ups: FollowUpRepositoryPort,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._follow_ups = follow_ups
        self._clock = clock

    @override
    def handle(self, command: CloseFollowUpCommand) -> FollowUp:
        actor = command.actor
        actor.require(PermissionCode.FOLLOW_UPS_MANAGE)
        note = Reason.parse(command.result_note)
        current = self._follow_ups.get(command.follow_up_id)
        if current is None:
            raise ResourceNotFoundError
        self._gate.enter(
            actor,
            PermissionCode.FOLLOW_UPS_MANAGE,
            current.patient_id,
            DataResource.TREATMENT_PLAN,
        )
        closed = current.close(outcome=command.outcome, note=note, at=self._clock.now())
        self._follow_ups.update(closed)
        return closed
