"""``clinic.sites`` and ``clinic.staff_sites`` under row level security (RF-15)."""

from __future__ import annotations

from typing import final, override
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.sites.ports import SiteRepositoryPort, StaffSitesRepositoryPort
from insumap.domain.clinic.site import NAME_TAKEN, Site, StaffSites, StaffSitesChange
from insumap.domain.common.errors import ConflictError
from insumap.infrastructure.persistence.orm import (
    ClinicOrm,
    SiteOrm,
    StaffProfileOrm,
    StaffSiteOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

NAME_INDEX = "ux_sites_clinic_name"

_SITES = select(SiteOrm, ClinicOrm.is_demo).join(
    ClinicOrm, ClinicOrm.id == SiteOrm.clinic_id
)


def _site(row: SiteOrm, *, is_demo: bool) -> Site:
    return Site(
        site_id=row.id,
        clinic_id=row.clinic_id,
        name=row.name,
        clinic_is_demo=is_demo,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@final
class SiteRepository(SiteRepositoryPort, StaffSitesRepositoryPort):
    """Sites and staff links of the session clinic; other clinics rows do not exist."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, site_id: UUID) -> Site | None:
        row = self._current.get().execute(_SITES.where(SiteOrm.id == site_id)).first()
        return None if row is None else _site(row[0], is_demo=row[1])

    @override
    def get_many(self, site_ids: frozenset[UUID]) -> tuple[Site, ...]:
        if not site_ids:
            return ()
        rows = self._current.get().execute(_SITES.where(SiteOrm.id.in_(site_ids))).all()
        return tuple(_site(row[0], is_demo=row[1]) for row in rows)

    @override
    def list_page(self, page: PageRequest) -> Page[Site]:
        statement = _SITES.order_by(SiteOrm.id)
        if page.after is not None:
            statement = statement.where(SiteOrm.id > page.after)
        rows = self._current.get().execute(statement.limit(page.limit + 1)).all()
        return build_page(
            [_site(row[0], is_demo=row[1]) for row in rows],
            limit=page.limit,
            key=lambda site: site.site_id,
        )

    @override
    def add(self, site: Site) -> None:
        session = self._current.get()
        session.add(
            SiteOrm(
                id=site.site_id,
                clinic_id=site.clinic_id,
                name=site.name,
                is_active=True,
                created_at=site.created_at,
                updated_at=site.updated_at,
            )
        )
        self._flush()

    @override
    def rename(self, site: Site) -> None:
        self._current.get().execute(
            update(SiteOrm)
            .where(SiteOrm.id == site.site_id)
            .values(name=site.name, updated_at=site.updated_at)
        )
        self._flush()

    @override
    def clinic_is_demo(self, clinic_id: UUID) -> bool | None:
        return self._current.get().scalar(
            select(ClinicOrm.is_demo).where(ClinicOrm.id == clinic_id)
        )

    @override
    def find_staff(self, user_id: UUID) -> StaffSites | None:
        session = self._current.get()
        row = session.execute(
            select(
                StaffProfileOrm.user_id, StaffProfileOrm.clinic_id, ClinicOrm.is_demo
            )
            .join(ClinicOrm, ClinicOrm.id == StaffProfileOrm.clinic_id)
            .where(StaffProfileOrm.user_id == user_id)
        ).first()
        if row is None:
            return None
        site_ids = session.scalars(
            select(StaffSiteOrm.site_id).where(StaffSiteOrm.user_id == user_id)
        ).all()
        return StaffSites(
            user_id=row[0],
            clinic_id=row[1],
            clinic_is_demo=row[2],
            site_ids=frozenset(site_ids),
        )

    @override
    def apply(self, change: StaffSitesChange) -> None:
        # No UPDATE grant on clinic.staff_sites: a replacement deletes and inserts.
        session = self._current.get()
        if change.removed:
            session.execute(
                delete(StaffSiteOrm).where(
                    StaffSiteOrm.user_id == change.user_id,
                    StaffSiteOrm.site_id.in_(change.removed),
                )
            )
        session.add_all(
            StaffSiteOrm(
                user_id=change.user_id,
                site_id=site_id,
                clinic_id=change.clinic_id,
                created_at=change.at,
            )
            for site_id in change.added
        )
        session.flush()

    def _flush(self) -> None:
        try:
            self._current.get().flush()
        except IntegrityError as error:
            if NAME_INDEX in str(error.orig):
                raise ConflictError(NAME_TAKEN) from None
            raise
