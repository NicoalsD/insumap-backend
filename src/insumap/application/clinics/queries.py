"""Reads of the clinics: the platform lists and reads them, staff reads their own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.clinics.ports import ClinicFilter, ClinicRepositoryPort
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.domain.clinic.clinic import Clinic, ClinicStatus
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ListClinicsInput:
    """The caller, the optional filters and the page asked for."""

    actor: Actor
    status: ClinicStatus | None
    is_demo: bool | None
    page: PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class GetClinicInput:
    """The caller and the clinic asked for."""

    actor: Actor
    clinic_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class GetCurrentClinicInput:
    """The caller only: the clinic comes from the token, never from the request."""

    actor: Actor


@final
class ListClinicsUseCase:
    """``GET /clinics``: the platform sees every clinic."""

    def __init__(self, *, uow: UnitOfWorkPort, clinics: ClinicRepositoryPort) -> None:
        self._uow = uow
        self._clinics = clinics

    def execute(self, input: ListClinicsInput) -> Page[Clinic]:
        """A page of clinics, oldest identifier first."""
        input.actor.require(PermissionCode.CLINICS_MANAGE)
        filters = ClinicFilter(status=input.status, is_demo=input.is_demo)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._clinics.list_clinics(filters, input.page)


@final
class GetClinicUseCase:
    """``GET /clinics/{clinic_id}``: a clinic that does not exist answers ``404``."""

    def __init__(self, *, uow: UnitOfWorkPort, clinics: ClinicRepositoryPort) -> None:
        self._uow = uow
        self._clinics = clinics

    def execute(self, input: GetClinicInput) -> Clinic:
        """The clinic with its suspension, if any."""
        input.actor.require(PermissionCode.CLINICS_MANAGE)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            clinic = self._clinics.get(input.clinic_id)
            if clinic is None:
                raise ResourceNotFoundError
            return clinic


@final
class GetCurrentClinicUseCase:
    """``GET /clinics/current``: the clinic of the caller, for any of its staff."""

    def __init__(self, *, uow: UnitOfWorkPort, clinics: ClinicRepositoryPort) -> None:
        self._uow = uow
        self._clinics = clinics

    def execute(self, input: GetCurrentClinicInput) -> Clinic:
        """The clinic the token belongs to; a caller without one has none to read."""
        actor = input.actor
        actor.require(PermissionCode.CLINICS_READ)
        if actor.clinic_id is None:
            raise ResourceNotFoundError
        with self._uow.begin(TransactionContext.for_actor(actor)):
            clinic = self._clinics.get(actor.clinic_id)
            if clinic is None:
                raise ResourceNotFoundError
            return clinic
