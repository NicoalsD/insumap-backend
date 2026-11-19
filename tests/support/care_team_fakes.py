"""In-memory care team repository and staff lookup."""

from __future__ import annotations

from typing import override
from uuid import UUID

from insumap.application.care_team.ports import (
    AssignmentFilter,
    CareTeamRepositoryPort,
    StaffLookupPort,
)
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.care_team.assignment import CareAssignment, CareTeam, CareTeamChange


class FakeCareTeams(CareTeamRepositoryPort):
    def __init__(self, *rows: CareAssignment) -> None:
        self.rows: dict[UUID, CareAssignment] = {r.assignment_id: r for r in rows}
        self.applied: list[CareTeamChange] = []

    @override
    def get_assignment(self, assignment_id: UUID) -> CareAssignment | None:
        return self.rows.get(assignment_id)

    @override
    def open_team(self, patient_id: UUID) -> CareTeam:
        return CareTeam(
            patient_id=patient_id,
            open_assignments=tuple(
                r
                for r in self.rows.values()
                if r.patient_id == patient_id and r.is_open
            ),
        )

    @override
    def apply(self, change: CareTeamChange) -> None:
        self.applied.append(change)
        for row in (*change.updated, *change.added):
            self.rows[row.assignment_id] = row

    @override
    def list_assignments(
        self, filters: AssignmentFilter, page: PageRequest
    ) -> Page[CareAssignment]:
        rows = sorted(self.rows.values(), key=lambda r: r.assignment_id)
        rows = [
            r
            for r in rows
            if (page.after is None or r.assignment_id > page.after)
            and (filters.patient_id is None or r.patient_id == filters.patient_id)
            and (filters.doctor_id is None or r.doctor_user_id == filters.doctor_id)
            and (filters.ended is None or (not r.is_open) == filters.ended)
        ]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda r: r.assignment_id
        )

    @override
    def count_open_for_doctor(self, doctor_user_id: UUID) -> int:
        return sum(
            1
            for r in self.rows.values()
            if r.doctor_user_id == doctor_user_id and r.is_open
        )


class FakeStaff(StaffLookupPort):
    def __init__(self, *doctors: UUID) -> None:
        self.doctors = set(doctors)

    @override
    def is_active_doctor(self, user_id: UUID) -> bool:
        return user_id in self.doctors
