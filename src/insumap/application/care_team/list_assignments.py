"""``GET /care-team/assignments``: who is assigned to whom, and the history."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import final
from uuid import UUID

from insumap.application.care_team.ports import AssignmentFilter, CareTeamRepositoryPort
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.domain.care_team.assignment import CareAssignment
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role


@dataclass(frozen=True, slots=True, kw_only=True)
class ListCareTeamAssignmentsInput:
    """The caller, the optional filters and the page asked for."""

    actor: Actor
    patient_id: UUID | None
    doctor_id: UUID | None
    ended: bool | None
    page: PageRequest


@final
class ListCareTeamAssignmentsUseCase:
    """An administrator sees the clinic; a doctor only the assignments that are his.

    The doctor's scope is applied here and again by row level security.
    """

    def __init__(self, *, uow: UnitOfWorkPort, teams: CareTeamRepositoryPort) -> None:
        self._uow = uow
        self._teams = teams

    def execute(self, input: ListCareTeamAssignmentsInput) -> Page[CareAssignment]:
        """A page of assignments, oldest first."""
        actor = input.actor
        actor.require(PermissionCode.CARE_TEAM_READ)
        filters = AssignmentFilter(
            patient_id=input.patient_id, doctor_id=input.doctor_id, ended=input.ended
        )
        if actor.role is Role.DOCTOR:
            filters = replace(filters, doctor_id=actor.user_id)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            return self._teams.list_assignments(filters, input.page)
