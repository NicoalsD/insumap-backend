"""``GET /patients/{patient_id}/clinical-notes``: the notes of an assigned patient."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.dashboard.ports import ClinicalNotePort
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.clinical_notes.note import ClinicalNote
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ListClinicalNotesInput:
    actor: Actor
    patient_id: UUID
    page: PageRequest


@final
class ListClinicalNotesUseCase:
    """Notes oldest first; the read is audited through the gate (P09) and committed.

    The administrator has no permission here: ``403`` before the patient lookup.
    """

    def __init__(
        self, *, uow: UnitOfWorkPort, gate: AssignedPatientGate, notes: ClinicalNotePort
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._notes = notes

    def execute(self, input: ListClinicalNotesInput) -> Page[ClinicalNote]:
        with self._uow.begin(TransactionContext.for_actor(input.actor)) as uow:
            patient_id = self._gate.enter(
                input.actor,
                PermissionCode.CLINICAL_NOTES_MANAGE,
                input.patient_id,
                DataResource.CLINICAL_NOTES,
            )
            page = self._notes.list(patient_id, input.page)
            uow.commit()  # keeps the audit row of the read (P09)
        return page
