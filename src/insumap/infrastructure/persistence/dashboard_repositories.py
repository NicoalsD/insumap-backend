"""Repositories of the triage, the reviews, the clinical notes and the clinic KPIs.

Each one runs under the row level security of the transaction it is called in:
the clinic and the role come from ``app.clinic_id`` and ``app.role``.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Final, final, override
from uuid import UUID

from sqlalchemy import func, select

from insumap.application.clinic_kpis.ports import ClinicKpiPort
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.dashboard.ports import (
    AssignedPatientRow,
    ClinicalNotePort,
    OpenAlertCountPort,
    TriageReviewPort,
    TriageRosterPort,
)
from insumap.domain.clinical_notes.note import ClinicalNote
from insumap.domain.dashboard.triage import TriageReview
from insumap.infrastructure.persistence.orm import (
    AlertOrm,
    CareAssignmentOrm,
    ClinicalNoteOrm,
    ClinicSettingsOrm,
    PatientOrm,
    TriageReviewOrm,
    UserOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.shared.errors import ErrorCode, InsumapError

OPEN_ALERT_STATUSES: Final = ("OPEN", "ESCALATED")


@final
class TriageRosterRepository(TriageRosterPort):
    """Patients with an open assignment of the doctor (care team table)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def assigned_patients(self, doctor_id: UUID) -> Sequence[AssignedPatientRow]:
        rows = self._current.get().execute(
            select(PatientOrm.id, PatientOrm.full_name)
            .join(CareAssignmentOrm, CareAssignmentOrm.patient_id == PatientOrm.id)
            .where(
                CareAssignmentOrm.doctor_user_id == doctor_id,
                CareAssignmentOrm.ended_at.is_(None),
            )
            .order_by(PatientOrm.id)
        )
        return [
            AssignedPatientRow(patient_id=row.id, full_name=row.full_name)
            for row in rows
        ]


@final
class OpenAlertCountRepository(OpenAlertCountPort):
    """One grouped query for the whole list: ``OPEN`` and ``ESCALATED`` alerts."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def open_counts(self, patient_ids: Collection[UUID]) -> Mapping[UUID, int]:
        if not patient_ids:
            return {}
        rows = self._current.get().execute(
            select(AlertOrm.patient_id, func.count(AlertOrm.id))
            .where(
                AlertOrm.patient_id.in_(list(patient_ids)),
                AlertOrm.status.in_(OPEN_ALERT_STATUSES),
            )
            .group_by(AlertOrm.patient_id)
        )
        return {row[0]: int(row[1]) for row in rows}


@final
class TriageReviewRepository(TriageReviewPort):
    """``care.triage_reviews``: insert only, read as the latest row per patient."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def latest_reviews(
        self, doctor_id: UUID, patient_ids: Collection[UUID]
    ) -> Mapping[UUID, datetime]:
        if not patient_ids:
            return {}
        rows = self._current.get().execute(
            select(TriageReviewOrm.patient_id, func.max(TriageReviewOrm.reviewed_at))
            .where(
                TriageReviewOrm.reviewed_by == doctor_id,
                TriageReviewOrm.patient_id.in_(list(patient_ids)),
            )
            .group_by(TriageReviewOrm.patient_id)
        )
        return {row[0]: row[1] for row in rows}

    @override
    def add(self, review: TriageReview) -> None:
        session = self._current.get()
        session.add(
            TriageReviewOrm(
                id=review.id,
                clinic_id=review.clinic_id,
                patient_id=review.patient_id,
                reviewed_by=review.reviewed_by,
                risk_assessment_id=None,
                window_days=review.window_days,
                reviewed_at=review.reviewed_at,
            )
        )
        session.flush()


def _note(row: ClinicalNoteOrm) -> ClinicalNote:
    return ClinicalNote(
        id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        author_user_id=row.author_user_id,
        body=row.body,
        supersedes_id=row.supersedes_id,
        created_at=row.created_at,
    )


@final
class ClinicalNoteRepository(ClinicalNotePort):
    """``care.clinical_notes``: insert only; keyset pages by the UUIDv7 key."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def add(self, note: ClinicalNote) -> None:
        session = self._current.get()
        session.add(
            ClinicalNoteOrm(
                id=note.id,
                clinic_id=note.clinic_id,
                patient_id=note.patient_id,
                author_user_id=note.author_user_id,
                body=note.body,
                supersedes_id=note.supersedes_id,
                created_at=note.created_at,
            )
        )
        session.flush()

    @override
    def find(self, patient_id: UUID, note_id: UUID) -> ClinicalNote | None:
        row = (
            self._current.get()
            .scalars(
                select(ClinicalNoteOrm).where(
                    ClinicalNoteOrm.id == note_id,
                    ClinicalNoteOrm.patient_id == patient_id,
                )
            )
            .first()
        )
        return None if row is None else _note(row)

    @override
    def list(self, patient_id: UUID, page: PageRequest) -> Page[ClinicalNote]:
        statement = select(ClinicalNoteOrm).where(
            ClinicalNoteOrm.patient_id == patient_id
        )
        if page.after is not None:
            statement = statement.where(ClinicalNoteOrm.id > page.after)
        rows = (
            self._current.get()
            .scalars(statement.order_by(ClinicalNoteOrm.id).limit(page.limit + 1))
            .all()
        )
        return build_page(
            [_note(row) for row in rows], limit=page.limit, key=lambda n: n.id
        )


@final
class ClinicKpiRepository(ClinicKpiPort):
    """Patients per account status and the small-cell setting, under RLS."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def patient_status_counts(self) -> Mapping[str, int]:
        rows = self._current.get().execute(
            select(UserOrm.status, func.count(PatientOrm.id))
            .select_from(PatientOrm)
            .join(UserOrm, UserOrm.id == PatientOrm.user_id)
            .group_by(UserOrm.status)
        )
        return {str(row[0]): int(row[1]) for row in rows}

    @override
    def min_cell_size(self) -> int:
        """The clinic row when it exists, else the global row (``clinic_id`` null)."""
        value = self._current.get().scalar(
            select(ClinicSettingsOrm.kpi_min_cell_size)
            .order_by(ClinicSettingsOrm.clinic_id.is_(None))
            .limit(1)
        )
        if value is None:
            raise InsumapError(ErrorCode.INTERNAL_ERROR)  # no global settings seeded
        return int(value)
