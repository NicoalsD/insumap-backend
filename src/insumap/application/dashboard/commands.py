"""Decisions of the doctor on the triage list and the clinical notes (P13).

Both are writes on clinical data: the gate of the assigned patient (P11, with
the audit of the read, P09) runs inside the transaction of the command, and the
command guard adds the audit row of the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.ids import IdGenerator
from insumap.application.dashboard.ports import ClinicalNotePort, TriageReviewPort
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.clinical_notes.note import ClinicalNote
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.dashboard.triage import TriageReview
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

REVIEW_ENTITY: Final = "TRIAGE_REVIEW"
NOTE_ENTITY: Final = "CLINICAL_NOTE"
ROLLING_DAY_WINDOW_DAYS: Final = 1
"""The rolling 24 hours of the triage window, counted as one day in the review row."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkPatientReviewedCommand(Command[TriageReview]):
    """The doctor marks an assigned patient as reviewed in the triage list."""

    audit_action: ClassVar[str] = "TRIAGE_PATIENT_REVIEWED"
    audit_entity_type: ClassVar[str] = REVIEW_ENTITY

    patient_id: UUID
    window_days: int

    @override
    def audit_subject(self, result: TriageReview) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.id,
            changed_fields=("reviewed_at",),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateClinicalNoteCommand(Command[ClinicalNote]):
    """The doctor writes a note about an assigned patient, or corrects one."""

    audit_action: ClassVar[str] = "CLINICAL_NOTE_CREATED"
    audit_entity_type: ClassVar[str] = NOTE_ENTITY

    patient_id: UUID
    text: str
    corrects_note_id: UUID | None

    @override
    def audit_subject(self, result: ClinicalNote) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.id,
            changed_fields=("body", "supersedes_id"),
        )


@final
class MarkPatientReviewedCommandHandler(
    CommandHandler[MarkPatientReviewedCommand, TriageReview]
):
    """Appends the review; the latest row of the doctor is the current one.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        reviews: TriageReviewPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._reviews = reviews
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: MarkPatientReviewedCommand) -> TriageReview:
        actor = command.actor
        patient_id = self._gate.enter(
            actor,
            PermissionCode.DASHBOARD_READ_ASSIGNED,
            command.patient_id,
            DataResource.TRIAGE_LIST,
        )
        if actor.clinic_id is None:
            raise ResourceNotFoundError
        review = TriageReview(
            id=self._ids.new_id(),
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            reviewed_by=actor.user_id,
            window_days=command.window_days,
            reviewed_at=self._clock.now(),
        )
        self._reviews.add(review)
        return review


@final
class CreateClinicalNoteCommandHandler(
    CommandHandler[CreateClinicalNoteCommand, ClinicalNote]
):
    """Appends a note; a correction must name a note of the same patient.

    Pattern: P13 Command
    """

    def __init__(
        self,
        *,
        gate: AssignedPatientGate,
        notes: ClinicalNotePort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._gate = gate
        self._notes = notes
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateClinicalNoteCommand) -> ClinicalNote:
        actor = command.actor
        patient_id = self._gate.enter(
            actor,
            PermissionCode.CLINICAL_NOTES_MANAGE,
            command.patient_id,
            DataResource.CLINICAL_NOTES,
        )
        if actor.clinic_id is None:
            raise ResourceNotFoundError
        if command.corrects_note_id is not None and (
            self._notes.find(patient_id, command.corrects_note_id) is None
        ):
            raise ResourceNotFoundError
        note = ClinicalNote(
            id=self._ids.new_id(),
            clinic_id=actor.clinic_id,
            patient_id=patient_id,
            author_user_id=actor.user_id,
            body=command.text,
            supersedes_id=command.corrects_note_id,
            created_at=self._clock.now(),
        )
        self._notes.add(note)
        return note
