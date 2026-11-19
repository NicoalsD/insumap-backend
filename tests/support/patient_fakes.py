"""In-memory doubles of the patient administration ports."""

from __future__ import annotations

from datetime import datetime
from typing import override
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.patients.ports import (
    PatientAdministrativeView,
    PatientRosterFilter,
    PatientRosterPort,
    PendingInvitationPort,
)


class FakePatientRoster(PatientRosterPort):
    """Views keyed by patient; the clinic scope is applied as the repository does."""

    def __init__(self, *views: PatientAdministrativeView) -> None:
        self.views: dict[UUID, PatientAdministrativeView] = {
            view.patient_id: view for view in views
        }

    @override
    def get(
        self, clinic_id: UUID, patient_id: UUID
    ) -> PatientAdministrativeView | None:
        view = self.views.get(patient_id)
        return view if view is not None and view.clinic_id == clinic_id else None

    @override
    def list(
        self, clinic_id: UUID, filters: PatientRosterFilter, page: PageRequest
    ) -> Page[PatientAdministrativeView]:
        rows = sorted(
            (view for view in self.views.values() if view.clinic_id == clinic_id),
            key=lambda view: view.patient_id,
        )
        rows = [
            view
            for view in rows
            if (page.after is None or view.patient_id > page.after)
            and (
                filters.account_status is None
                or view.account_status is filters.account_status
            )
            and (not filters.without_doctor or view.assigned_doctor_count == 0)
        ]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda view: view.patient_id
        )


class FakePendingInvitations(PendingInvitationPort):
    """Keeps which account had its pending invitations revoked, and by whom."""

    def __init__(self) -> None:
        self.revoked: list[tuple[UUID, UUID]] = []

    @override
    def revoke_pending(self, user_id: UUID, *, revoked_by: UUID, now: datetime) -> None:
        self.revoked.append((user_id, revoked_by))
