"""Sites of a clinic and the staff members who work at them (RF-15, Post-MVP).

A staff member belongs to any number of sites of its own clinic. Replacing the
sites of a staff member returns the links to delete and to insert; the use case
writes them in one transaction. Names are unique per clinic, ignoring case, and
that rule lives in the database (``ux_sites_clinic_name``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final
from uuid import UUID

from insumap.domain.common.text import clean_text
from insumap.shared.field_limits import FieldLimits

NAME_TAKEN: Final = "site_name_taken"
"""Reason of the ``409`` when a site name repeats within the clinic."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Site:
    """A site of a clinic. ``clinic_is_demo`` marks the simulated data of the clinic."""

    site_id: UUID
    clinic_id: UUID
    name: str
    clinic_is_demo: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        site_id: UUID,
        clinic_id: UUID,
        name: str,
        clinic_is_demo: bool,
        at: datetime,
    ) -> Site:
        """A new site from raw input; blank or over long names are a ``422``."""
        return cls(
            site_id=site_id,
            clinic_id=clinic_id,
            name=_clean_name(name),
            clinic_is_demo=clinic_is_demo,
            created_at=at,
            updated_at=at,
        )

    def renamed(self, name: str, *, at: datetime) -> Site:
        """This site with a new name, stamped with ``at``."""
        return replace(self, name=_clean_name(name), updated_at=at)


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffSitesChange:
    """The links of one staff member to delete and to insert, stamped with ``at``."""

    user_id: UUID
    clinic_id: UUID
    added: frozenset[UUID]
    removed: frozenset[UUID]
    at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffSites:
    """A staff member of a clinic and the sites it works at, as read."""

    user_id: UUID
    clinic_id: UUID
    clinic_is_demo: bool
    site_ids: frozenset[UUID]

    def change_to(
        self, requested: frozenset[UUID], *, at: datetime
    ) -> StaffSitesChange:
        """The links that replacing the current sites with ``requested`` changes."""
        return StaffSitesChange(
            user_id=self.user_id,
            clinic_id=self.clinic_id,
            added=requested - self.site_ids,
            removed=self.site_ids - requested,
            at=at,
        )

    def with_sites(self, requested: frozenset[UUID]) -> StaffSites:
        """This staff member after the replacement, as the caller will see it."""
        return replace(self, site_ids=requested)


def _clean_name(raw: str) -> str:
    return clean_text(
        raw, field="body.name", max_length=FieldLimits.SITE_NAME_MAX_LENGTH
    )
