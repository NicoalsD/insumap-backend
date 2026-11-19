"""In-memory doubles of the patient administration ports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import override
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.identity.ports import UserRepositoryPort
from insumap.application.patients.ports import (
    PatientAdministrativeView,
    PatientRosterFilter,
    PatientRosterPort,
    PendingInvitationPort,
)


class FakePatientRoster(PatientRosterPort):
    """Views keyed by patient; the clinic scope is applied as the repository does.

    With ``users`` and ``user_of``, the account status is read from the user
    double, as the query reads ``iam.users``: a change made by a command shows up.
    """

    def __init__(
        self,
        *views: PatientAdministrativeView,
        users: UserRepositoryPort | None = None,
        user_of: Mapping[UUID, UUID] | None = None,
    ) -> None:
        self.views: dict[UUID, PatientAdministrativeView] = {
            view.patient_id: view for view in views
        }
        self._users = users
        self._user_of = dict(user_of or {})

    def _current(self, view: PatientAdministrativeView) -> PatientAdministrativeView:
        if self._users is None or view.patient_id not in self._user_of:
            return view
        account = self._users.get(self._user_of[view.patient_id])
        return view if account is None else replace(view, account_status=account.status)

    @override
    def get(
        self, clinic_id: UUID, patient_id: UUID
    ) -> PatientAdministrativeView | None:
        view = self.views.get(patient_id)
        if view is None or view.clinic_id != clinic_id:
            return None
        return self._current(view)

    @override
    def list(
        self, clinic_id: UUID, filters: PatientRosterFilter, page: PageRequest
    ) -> Page[PatientAdministrativeView]:
        rows = sorted(
            (
                self._current(view)
                for view in self.views.values()
                if view.clinic_id == clinic_id
            ),
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
