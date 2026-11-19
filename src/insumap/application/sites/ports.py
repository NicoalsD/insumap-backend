"""Ports of the sites use cases: sites and the sites of each staff member."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.clinic.site import Site, StaffSites, StaffSitesChange


class SiteRepositoryPort(ABC):
    """Sites of the session clinic, under row level security.

    A site of another clinic is never returned by ``list_page`` or
    ``get_many``; ``get`` may return it, and the handler checks the clinic.
    """

    @abstractmethod
    def get(self, site_id: UUID) -> Site | None:
        """One site, or ``None`` if the session cannot see it."""

    @abstractmethod
    def get_many(self, site_ids: frozenset[UUID]) -> tuple[Site, ...]:
        """The sites among ``site_ids`` that the session can see."""

    @abstractmethod
    def list_page(self, page: PageRequest) -> Page[Site]:
        """A page of the sites of the session clinic, by identifier."""

    @abstractmethod
    def add(self, site: Site) -> None:
        """Insert a site; a name repeated in the clinic raises ``ConflictError``."""

    @abstractmethod
    def rename(self, site: Site) -> None:
        """Update the name of a site; a repeated name raises ``ConflictError``."""

    @abstractmethod
    def clinic_is_demo(self, clinic_id: UUID) -> bool | None:
        """Whether the clinic is the demo one, or ``None`` if it is not visible."""


class StaffSitesRepositoryPort(ABC):
    """The sites each staff member works at, under row level security."""

    @abstractmethod
    def find_staff(self, user_id: UUID) -> StaffSites | None:
        """A staff member of the session clinic with its sites, or ``None``."""

    @abstractmethod
    def apply(self, change: StaffSitesChange) -> None:
        """Delete the removed links and insert the added ones."""
