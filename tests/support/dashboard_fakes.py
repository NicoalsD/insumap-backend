"""In-memory doubles of the dashboard ports (triage, reviews, notes and KPIs)."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from uuid import UUID

from insumap.application.access.ports import DataAccessLogPort, DataAccessRecord
from insumap.application.alerts.ports import AlertSummary, AlertSummaryPort
from insumap.application.clinic_kpis.ports import ClinicKpiPort
from insumap.application.common.pagination import Page, PageRequest, encode_cursor
from insumap.application.dashboard.ports import (
    AssignedPatientRow,
    ClinicalNotePort,
    OpenAlertCountPort,
    TriageReviewPort,
    TriageRosterPort,
)
from insumap.domain.clinical_notes.note import ClinicalNote
from insumap.domain.dashboard.triage import TriageReview


class FakeRoster(TriageRosterPort):
    def __init__(self, rows: Mapping[UUID, Sequence[AssignedPatientRow]]) -> None:
        self.rows = dict(rows)

    def assigned_patients(self, doctor_id: UUID) -> Sequence[AssignedPatientRow]:
        return list(self.rows.get(doctor_id, []))


class FakeOpenAlerts(OpenAlertCountPort):
    def __init__(self, counts: Mapping[UUID, int] | None = None) -> None:
        self.counts = dict(counts or {})

    def open_counts(self, patient_ids: Collection[UUID]) -> Mapping[UUID, int]:
        return {p: self.counts[p] for p in patient_ids if self.counts.get(p)}


class FakeReviews(TriageReviewPort):
    def __init__(self) -> None:
        self.rows: list[TriageReview] = []

    def latest_reviews(
        self, doctor_id: UUID, patient_ids: Collection[UUID]
    ) -> Mapping[UUID, datetime]:
        latest: dict[UUID, datetime] = {}
        for row in self.rows:
            if row.reviewed_by == doctor_id and row.patient_id in patient_ids:
                previous = latest.get(row.patient_id)
                if previous is None or row.reviewed_at > previous:
                    latest[row.patient_id] = row.reviewed_at
        return latest

    def add(self, review: TriageReview) -> None:
        self.rows.append(review)


class FakeNotes(ClinicalNotePort):
    def __init__(self) -> None:
        self.rows: list[ClinicalNote] = []

    def add(self, note: ClinicalNote) -> None:
        self.rows.append(note)

    def find(self, patient_id: UUID, note_id: UUID) -> ClinicalNote | None:
        return next(
            (n for n in self.rows if n.id == note_id and n.patient_id == patient_id),
            None,
        )

    def list(self, patient_id: UUID, page: PageRequest) -> Page[ClinicalNote]:
        rows = sorted(
            (n for n in self.rows if n.patient_id == patient_id), key=lambda n: n.id
        )
        if page.after is not None:
            rows = [n for n in rows if n.id > page.after]
        cut = rows[: page.limit]
        more = len(rows) > page.limit
        return Page(
            items=cut, next_cursor=encode_cursor(cut[-1].id) if more and cut else None
        )


class FakeAudit(DataAccessLogPort):
    """Keeps the granted rows and counts the batch writes (one per list)."""

    def __init__(self) -> None:
        self.granted: list[DataAccessRecord] = []
        self.batches: list[int] = []

    def record_granted(self, record: DataAccessRecord) -> None:
        self.granted.append(record)

    def record_granted_many(self, records: Sequence[DataAccessRecord]) -> None:
        self.batches.append(len(records))
        self.granted.extend(records)

    def record_denied(self, record: DataAccessRecord) -> None:
        pass


class FakeKpis(ClinicKpiPort):
    def __init__(self, counts: Mapping[str, int], min_cell: int = 1) -> None:
        self.counts = dict(counts)
        self.min_cell = min_cell

    def patient_status_counts(self) -> Mapping[str, int]:
        return dict(self.counts)

    def min_cell_size(self) -> int:
        return self.min_cell


class FakeAlertSummary(AlertSummaryPort):
    def __init__(self, summary: AlertSummary) -> None:
        self._summary = summary

    def summary(self) -> AlertSummary:
        return self._summary
