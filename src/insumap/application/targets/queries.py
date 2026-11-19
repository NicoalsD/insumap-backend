"""Reads of the target profile catalog (API.md 8.7): listing and detail."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.targets.ports import TargetProfileCatalogPort
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.target_profile_version import TargetProfileVersion

CATALOG_READ_PERMISSIONS: frozenset[PermissionCode] = frozenset(
    {PermissionCode.TARGET_PROFILES_MANAGE, PermissionCode.TARGET_PROFILES_ASSIGN}
)
"""Either permission reads the catalog: the administrator and the doctor."""


def require_catalog_read(actor: Actor) -> None:
    """Any of the two catalog permissions; the check is in the use case."""
    if not actor.permissions & CATALOG_READ_PERMISSIONS:
        raise PermissionDeniedError


@dataclass(frozen=True, slots=True, kw_only=True)
class ListTargetProfilesInput:
    actor: Actor
    population: str | None
    page: PageRequest


@final
class ListTargetProfilesUseCase:
    """Active profiles of the clinic and the seeds, with their version."""

    def __init__(
        self, *, uow: UnitOfWorkPort, catalog: TargetProfileCatalogPort
    ) -> None:
        self._uow = uow
        self._catalog = catalog

    def execute(self, input: ListTargetProfilesInput) -> Page[TargetProfileVersion]:
        require_catalog_read(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._catalog.list_active(input.population, input.page)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetProfileDetail:
    """A profile and the history of its versions (the current one included)."""

    profile: TargetProfileVersion
    versions: tuple[TargetProfileVersion, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class GetTargetProfileInput:
    actor: Actor
    profile_id: UUID


@final
class GetTargetProfileUseCase:
    """One profile with every version of its code."""

    def __init__(
        self, *, uow: UnitOfWorkPort, catalog: TargetProfileCatalogPort
    ) -> None:
        self._uow = uow
        self._catalog = catalog

    def execute(self, input: GetTargetProfileInput) -> TargetProfileDetail:
        require_catalog_read(input.actor)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            profile = self._catalog.get(input.profile_id)
            if profile is None:
                raise ResourceNotFoundError
            versions = self._catalog.versions_of(profile.clinic_id, profile.code)
            return TargetProfileDetail(profile=profile, versions=versions)
