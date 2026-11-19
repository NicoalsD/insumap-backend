"""In-memory sites and staff sites, with the rules of the database.

The fake keeps sites of every clinic, as a test may need one of another clinic;
``list_page`` and ``clinic_is_demo`` answer for the session clinic only, like
row level security does. Names are unique per clinic, ignoring case.
"""

from __future__ import annotations

from typing import override
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.sites.ports import SiteRepositoryPort, StaffSitesRepositoryPort
from insumap.domain.clinic.site import NAME_TAKEN, Site, StaffSites, StaffSitesChange
from insumap.domain.common.errors import ConflictError


class FakeSites(SiteRepositoryPort, StaffSitesRepositoryPort):
    def __init__(self, *, clinic_id: UUID, is_demo: bool = True) -> None:
        self.clinic_id = clinic_id
        self.is_demo = is_demo
        self.sites: dict[UUID, Site] = {}
        self.staff: dict[UUID, StaffSites] = {}
        self.applied: list[StaffSitesChange] = []

    def add_staff(self, user_id: UUID, clinic_id: UUID, *sites: UUID) -> None:
        self.staff[user_id] = StaffSites(
            user_id=user_id,
            clinic_id=clinic_id,
            clinic_is_demo=self.is_demo,
            site_ids=frozenset(sites),
        )

    def _assert_unique(self, site: Site) -> None:
        taken = any(
            other.clinic_id == site.clinic_id
            and other.site_id != site.site_id
            and other.name.casefold() == site.name.casefold()
            for other in self.sites.values()
        )
        if taken:
            raise ConflictError(NAME_TAKEN)

    @override
    def get(self, site_id: UUID) -> Site | None:
        return self.sites.get(site_id)

    @override
    def get_many(self, site_ids: frozenset[UUID]) -> tuple[Site, ...]:
        return tuple(self.sites[s] for s in site_ids if s in self.sites)

    @override
    def list_page(self, page: PageRequest) -> Page[Site]:
        rows = sorted(
            (
                site
                for site in self.sites.values()
                if site.clinic_id == self.clinic_id
                and (page.after is None or site.site_id > page.after)
            ),
            key=lambda site: site.site_id,
        )
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda site: site.site_id
        )

    @override
    def add(self, site: Site) -> None:
        self._assert_unique(site)
        self.sites[site.site_id] = site

    @override
    def rename(self, site: Site) -> None:
        self._assert_unique(site)
        self.sites[site.site_id] = site

    @override
    def clinic_is_demo(self, clinic_id: UUID) -> bool | None:
        return self.is_demo if clinic_id == self.clinic_id else None

    @override
    def find_staff(self, user_id: UUID) -> StaffSites | None:
        return self.staff.get(user_id)

    @override
    def apply(self, change: StaffSitesChange) -> None:
        self.applied.append(change)
        current = self.staff[change.user_id]
        self.staff[change.user_id] = current.with_sites(
            (current.site_ids - change.removed) | change.added
        )
