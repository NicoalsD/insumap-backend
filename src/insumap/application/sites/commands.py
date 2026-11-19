"""Decisions about sites: create, rename and set the sites of a staff member (P13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final, final, override
from uuid import UUID

from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.sites.ports import SiteRepositoryPort, StaffSitesRepositoryPort
from insumap.domain.clinic.site import Site, StaffSites
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.time import Clock

SITE_ENTITY: Final = "SITE"
STAFF_SITES_ENTITY: Final = "STAFF_SITES"


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateSiteCommand(Command[Site]):
    """The clinic administrator adds a site to the clinic."""

    audit_action: ClassVar[str] = "SITE_CREATED"
    audit_entity_type: ClassVar[str] = SITE_ENTITY

    name: str

    @override
    def audit_subject(self, result: Site) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.site_id,
            changed_fields=("name",),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateSiteCommand(Command[Site]):
    """The clinic administrator renames a site of the clinic."""

    audit_action: ClassVar[str] = "SITE_UPDATED"
    audit_entity_type: ClassVar[str] = SITE_ENTITY

    site_id: UUID
    name: str

    @override
    def audit_subject(self, result: Site) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.site_id,
            changed_fields=("name",),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SetUserSitesCommand(Command[StaffSites]):
    """The clinic administrator replaces the sites where a staff member works."""

    audit_action: ClassVar[str] = "STAFF_SITES_CHANGED"
    audit_entity_type: ClassVar[str] = STAFF_SITES_ENTITY

    user_id: UUID
    site_ids: frozenset[UUID]

    @override
    def audit_subject(self, result: StaffSites) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.user_id,
            changed_fields=("site_ids",),
        )


@final
class CreateSiteCommandHandler(CommandHandler[CreateSiteCommand, Site]):
    """Adds a site to the clinic of the administrator."""

    def __init__(
        self, *, sites: SiteRepositoryPort, ids: IdGenerator, clock: Clock
    ) -> None:
        self._sites = sites
        self._ids = ids
        self._clock = clock

    @override
    def handle(self, command: CreateSiteCommand) -> Site:
        actor = command.actor
        actor.require(PermissionCode.SITES_MANAGE)
        clinic_id = _session_clinic(actor)
        is_demo = self._sites.clinic_is_demo(clinic_id)
        if is_demo is None:
            raise ResourceNotFoundError
        site = Site.create(
            site_id=self._ids.new_id(),
            clinic_id=clinic_id,
            name=command.name,
            clinic_is_demo=is_demo,
            at=self._clock.now(),
        )
        self._sites.add(site)
        return site


@final
class UpdateSiteCommandHandler(CommandHandler[UpdateSiteCommand, Site]):
    """Renames a site of the clinic of the administrator."""

    def __init__(self, *, sites: SiteRepositoryPort, clock: Clock) -> None:
        self._sites = sites
        self._clock = clock

    @override
    def handle(self, command: UpdateSiteCommand) -> Site:
        actor = command.actor
        actor.require(PermissionCode.SITES_MANAGE)
        site = self._sites.get(command.site_id)
        if site is None or site.clinic_id != _session_clinic(actor):
            raise ResourceNotFoundError
        renamed = site.renamed(command.name, at=self._clock.now())
        self._sites.rename(renamed)
        return renamed


@final
class SetUserSitesCommandHandler(CommandHandler[SetUserSitesCommand, StaffSites]):
    """Replaces the sites of a staff member; every site must be of the clinic."""

    def __init__(
        self,
        *,
        sites: SiteRepositoryPort,
        staff_sites: StaffSitesRepositoryPort,
        clock: Clock,
    ) -> None:
        self._sites = sites
        self._staff_sites = staff_sites
        self._clock = clock

    @override
    def handle(self, command: SetUserSitesCommand) -> StaffSites:
        actor = command.actor
        actor.require(PermissionCode.SITES_MANAGE)
        clinic_id = _session_clinic(actor)
        staff = self._staff_sites.find_staff(command.user_id)
        if staff is None or staff.clinic_id != clinic_id:
            raise ResourceNotFoundError
        requested = command.site_ids
        if requested:
            found = {
                site.site_id
                for site in self._sites.get_many(requested)
                if site.clinic_id == clinic_id
            }
            if not requested <= found:
                raise ResourceNotFoundError
        self._staff_sites.apply(staff.change_to(requested, at=self._clock.now()))
        return staff.with_sites(requested)


def _session_clinic(actor: Actor) -> UUID:
    """The clinic of the token; a caller without one sees no clinic data."""
    if actor.clinic_id is None:
        raise ResourceNotFoundError
    return actor.clinic_id
