"""``GET /sites``: the sites of the clinic of the administrator, by identifier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.sites.ports import SiteRepositoryPort
from insumap.domain.clinic.site import Site
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ListSitesInput:
    """The caller and the page asked for."""

    actor: Actor
    page: PageRequest


@final
class ListSitesUseCase:
    """Lists the sites of the session clinic; row level security applies as well."""

    def __init__(self, *, uow: UnitOfWorkPort, sites: SiteRepositoryPort) -> None:
        self._uow = uow
        self._sites = sites

    def execute(self, input: ListSitesInput) -> Page[Site]:
        """A page of sites, oldest identifier first."""
        input.actor.require(PermissionCode.SITES_MANAGE)
        with self._uow.begin(TransactionContext.for_actor(input.actor)):
            return self._sites.list_page(input.page)
