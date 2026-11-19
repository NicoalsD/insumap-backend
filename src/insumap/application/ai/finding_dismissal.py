"""The doctor dismisses a pattern finding of an assigned patient (RF-68, P13)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.ai.records import (
    PatternFindingReadPort,
    PatternFindingReviewPort,
    PatternFindingView,
)
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.ai.finding_review import FindingDismissal, parse_dismissal_note
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

FINDING_ENTITY: Final = "PATTERN_FINDING"
FINDING_MACHINE: Final = "PATTERN_FINDING"
DISMISS_CHANGED_FIELDS: Final = ("status", "dismissed_by", "dismissed_at")


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class DismissPatternFindingCommand(Command[PatternFindingView]):
    """The doctor dismisses a finding; the note is mandatory and kept in the audit.

    Pattern: P13 Command
    """

    audit_action: ClassVar[str] = "PATTERN_FINDING_DISMISSED"
    audit_entity_type: ClassVar[str] = FINDING_ENTITY

    patient_id: UUID
    finding_id: UUID
    note: str

    @override
    def audit_subject(self, result: PatternFindingView) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.finding_id,
            reason=self.note.strip(),
            changed_fields=DISMISS_CHANGED_FIELDS,
        )


@final
class DismissPatternFindingCommandHandler(
    CommandHandler[DismissPatternFindingCommand, PatternFindingView]
):
    """Appends the dismissal of an assigned patient's finding, once.

    A patient who is not assigned, or a finding that is not theirs, answers the same
    ``404``. A finding already dismissed answers ``409 INVALID_STATE_TRANSITION``.
    The write is one row; the caller's transaction and the audit commit with it.
    """

    def __init__(
        self,
        *,
        assigned_gate: AssignedPatientGate,
        findings: PatternFindingReadPort,
        reviews: PatternFindingReviewPort,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._assigned = assigned_gate
        self._findings = findings
        self._reviews = reviews
        self._clock = clock
        self._ids = ids

    @override
    def handle(self, command: DismissPatternFindingCommand) -> PatternFindingView:
        actor = command.actor
        actor.require(PermissionCode.AI_RISK_READ_ASSIGNED)
        note = parse_dismissal_note(command.note)
        self._assigned.enter(
            actor,
            PermissionCode.AI_RISK_READ_ASSIGNED,
            command.patient_id,
            DataResource.AI_OUTPUTS,
        )
        clinic_id = actor.clinic_id
        if clinic_id is None:
            raise PermissionDeniedError
        current = self._findings.get_for_patient(command.patient_id, command.finding_id)
        if current is None:
            raise ResourceNotFoundError
        if current.dismissed_at is not None:
            raise InvalidStateTransitionError(
                FINDING_MACHINE, current.status, "DISMISS"
            )
        now = self._clock.now()
        self._reviews.add(
            FindingDismissal(
                dismissal_id=self._ids.new_id(),
                clinic_id=clinic_id,
                patient_id=command.patient_id,
                finding_id=current.finding_id,
                note=note,
                reviewed_by=actor.user_id,
                reviewed_at=now,
            )
        )
        return replace(current, dismissed_at=now, dismissed_by=actor.user_id)
