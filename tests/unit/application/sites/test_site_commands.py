"""Site commands (P13) and the listing, with doubles of the ports (no DB)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.application.commands.auditing import AuditingCommandHandler
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import PageRequest, decode_cursor
from insumap.application.sites.commands import (
    CreateSiteCommand,
    CreateSiteCommandHandler,
    SetUserSitesCommand,
    SetUserSitesCommandHandler,
    UpdateSiteCommand,
    UpdateSiteCommandHandler,
)
from insumap.application.sites.list_sites import ListSitesInput, ListSitesUseCase
from insumap.domain.clinic.site import NAME_TAKEN, Site
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role
from tests.support.commands import InMemoryAuditLog
from tests.support.fixed_clock import FixedClock
from tests.support.identity_fakes import FakeIds, FakeUnitOfWorkPort
from tests.support.sites_fakes import FakeSites

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 19, 13, 0, tzinfo=UTC)
CLINIC = UUID(int=10)
OTHER_CLINIC = UUID(int=11)
ADMIN = UUID(int=3)
STAFF = UUID(int=40)
OTHER_STAFF = UUID(int=41)
NORTH = UUID(int=50)
SOUTH = UUID(int=51)
FOREIGN_SITE = UUID(int=60)
SITE_PERMISSIONS = frozenset({PermissionCode.SITES_MANAGE})


def admin(
    permissions: frozenset[PermissionCode] = SITE_PERMISSIONS,
    clinic_id: UUID | None = CLINIC,
) -> Actor:
    return Actor(
        user_id=ADMIN,
        clinic_id=clinic_id,
        role=Role.CLINIC_ADMIN,
        permissions=permissions,
        requires_mfa=True,
        mfa_verified=True,
    )


def site(site_id: UUID, name: str, clinic: UUID = CLINIC) -> Site:
    return Site.create(
        site_id=site_id,
        clinic_id=clinic,
        name=name,
        clinic_is_demo=True,
        at=NOW,
    )


class World:
    def __init__(self) -> None:
        self.sites = FakeSites(clinic_id=CLINIC)
        self.sites.sites = {
            NORTH: site(NORTH, "Sede Norte"),
            SOUTH: site(SOUTH, "Sede Sur"),
            FOREIGN_SITE: site(FOREIGN_SITE, "Sede Ajena", clinic=OTHER_CLINIC),
        }
        self.sites.add_staff(STAFF, CLINIC, NORTH)
        self.sites.add_staff(OTHER_STAFF, OTHER_CLINIC)
        self.clock = FixedClock(NOW)
        self.ids = FakeIds()
        self.audit = InMemoryAuditLog()
        self.create = CreateSiteCommandHandler(
            sites=self.sites, ids=self.ids, clock=self.clock
        )
        self.update = UpdateSiteCommandHandler(sites=self.sites, clock=self.clock)
        self.set_user = SetUserSitesCommandHandler(
            sites=self.sites, staff_sites=self.sites, clock=self.clock
        )


def test_create_adds_a_trimmed_site_of_the_clinic_and_is_audited() -> None:
    world = World()
    audited = AuditingCommandHandler(world.create, world.audit, world.clock)

    created = audited.handle(CreateSiteCommand(actor=admin(), name="  Sede Oriente "))

    assert created.name == "Sede Oriente"
    assert created.clinic_id == CLINIC
    assert created.clinic_is_demo is True
    assert created.created_at == NOW
    assert world.sites.sites[created.site_id] == created
    [entry] = world.audit.entries
    assert entry.action == "SITE_CREATED"
    assert entry.entity_type == "SITE"
    assert entry.entity_id == created.site_id
    assert entry.changed_fields == ("name",)


def test_create_needs_the_permission() -> None:
    world = World()

    with pytest.raises(PermissionDeniedError):
        world.create.handle(
            CreateSiteCommand(actor=admin(frozenset()), name="Sede Oriente")
        )


def test_create_refuses_a_name_already_taken_ignoring_case() -> None:
    world = World()

    with pytest.raises(ConflictError) as error:
        world.create.handle(CreateSiteCommand(actor=admin(), name="SEDE norte"))

    assert error.value.detail == {"reason": NAME_TAKEN}


def test_create_without_a_clinic_is_not_found() -> None:
    world = World()

    with pytest.raises(ResourceNotFoundError):
        world.create.handle(
            CreateSiteCommand(actor=admin(clinic_id=None), name="Sede Oriente")
        )


def test_rename_keeps_the_site_and_moves_only_the_update_date() -> None:
    world = World()
    handler = UpdateSiteCommandHandler(sites=world.sites, clock=FixedClock(LATER))

    renamed = handler.handle(
        UpdateSiteCommand(actor=admin(), site_id=NORTH, name="Sede Norte Dos")
    )

    assert renamed.site_id == NORTH
    assert renamed.name == "Sede Norte Dos"
    assert renamed.created_at == NOW
    assert renamed.updated_at == LATER


def test_rename_of_another_clinics_site_is_not_found_and_changes_nothing() -> None:
    world = World()

    with pytest.raises(ResourceNotFoundError):
        world.update.handle(
            UpdateSiteCommand(actor=admin(), site_id=FOREIGN_SITE, name="Robada")
        )

    assert world.sites.sites[FOREIGN_SITE].name == "Sede Ajena"


def test_rename_of_an_unknown_site_is_not_found() -> None:
    world = World()

    with pytest.raises(ResourceNotFoundError):
        world.update.handle(
            UpdateSiteCommand(actor=admin(), site_id=UUID(int=999), name="Nueva")
        )


def test_rename_to_a_name_of_another_site_of_the_clinic_conflicts() -> None:
    world = World()

    with pytest.raises(ConflictError):
        world.update.handle(
            UpdateSiteCommand(actor=admin(), site_id=NORTH, name="sede SUR")
        )


def test_set_user_sites_replaces_the_links_and_returns_the_staff() -> None:
    world = World()

    result = world.set_user.handle(
        SetUserSitesCommand(
            actor=admin(), user_id=STAFF, site_ids=frozenset({SOUTH, SOUTH})
        )
    )

    assert result.user_id == STAFF
    assert result.site_ids == frozenset({SOUTH})
    [change] = world.sites.applied
    assert change.added == frozenset({SOUTH})
    assert change.removed == frozenset({NORTH})
    assert change.at == NOW


def test_an_empty_list_removes_every_site_of_the_staff() -> None:
    world = World()

    result = world.set_user.handle(
        SetUserSitesCommand(actor=admin(), user_id=STAFF, site_ids=frozenset())
    )

    assert result.site_ids == frozenset()
    assert world.sites.staff[STAFF].site_ids == frozenset()


@pytest.mark.parametrize(
    ("user_id", "site_ids"),
    [
        (UUID(int=999), frozenset({SOUTH})),  # unknown user
        (OTHER_STAFF, frozenset({SOUTH})),  # staff of another clinic
        (STAFF, frozenset({SOUTH, FOREIGN_SITE})),  # site of another clinic
        (STAFF, frozenset({UUID(int=999)})),  # unknown site
    ],
)
def test_set_user_sites_refuses_what_is_not_of_the_clinic(
    user_id: UUID, site_ids: frozenset[UUID]
) -> None:
    world = World()

    with pytest.raises(ResourceNotFoundError):
        world.set_user.handle(
            SetUserSitesCommand(actor=admin(), user_id=user_id, site_ids=site_ids)
        )

    assert world.sites.applied == []


def test_set_user_sites_needs_the_permission() -> None:
    world = World()

    with pytest.raises(PermissionDeniedError):
        world.set_user.handle(
            SetUserSitesCommand(
                actor=admin(frozenset()), user_id=STAFF, site_ids=frozenset()
            )
        )


def test_listing_shows_only_the_clinic_and_pages_by_identifier() -> None:
    world = World()
    use_case = ListSitesUseCase(uow=FakeUnitOfWorkPort(), sites=world.sites)

    first = use_case.execute(ListSitesInput(actor=admin(), page=PageRequest(limit=1)))
    second = use_case.execute(
        ListSitesInput(
            actor=admin(),
            page=PageRequest(limit=1, after=decode_cursor(first.next_cursor)),
        )
    )

    assert [s.site_id for s in first.items] == [NORTH]
    assert first.next_cursor is not None
    assert [s.site_id for s in second.items] == [SOUTH]
    assert second.next_cursor is None


def test_listing_needs_the_permission() -> None:
    world = World()
    use_case = ListSitesUseCase(uow=FakeUnitOfWorkPort(), sites=world.sites)

    with pytest.raises(PermissionDeniedError):
        use_case.execute(
            ListSitesInput(actor=admin(frozenset()), page=PageRequest(limit=10))
        )
