"""``GET /users`` and ``GET /users/{user_id}``: the staff of the caller's clinic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.users.access import clinic_of
from insumap.application.users.ports import StaffDirectoryPort, StaffFilter, StaffMember
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ListStaffInput:
    """The caller, the optional filters and the page asked for."""

    actor: Actor
    filters: StaffFilter
    page: PageRequest


@final
class ListStaffUseCase:
    """A page of the staff of the caller's clinic, by identifier."""

    def __init__(self, *, uow: UnitOfWorkPort, directory: StaffDirectoryPort) -> None:
        self._uow = uow
        self._directory = directory

    def execute(self, input: ListStaffInput) -> Page[StaffMember]:
        """Only ``users.read``; the clinic comes from the token, never the request."""
        input.actor.require(PermissionCode.USERS_READ)
        clinic_id = clinic_of(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._directory.list(clinic_id, input.filters, input.page)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetStaffInput:
    """The caller and the staff member asked for."""

    actor: Actor
    user_id: UUID


@final
class GetStaffUseCase:
    """One staff member of the caller's clinic; anyone else is ``404``."""

    def __init__(self, *, uow: UnitOfWorkPort, directory: StaffDirectoryPort) -> None:
        self._uow = uow
        self._directory = directory

    def execute(self, input: GetStaffInput) -> StaffMember:
        """Only ``users.read``; patients and other clinics' staff are not found."""
        input.actor.require(PermissionCode.USERS_READ)
        clinic_id = clinic_of(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            member = self._directory.get(clinic_id, input.user_id)
        if member is None:
            raise ResourceNotFoundError
        return member
