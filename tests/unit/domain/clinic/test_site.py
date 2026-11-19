"""Site and StaffSites: names, renames and the links a replacement changes."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from insumap.domain.clinic.site import Site, StaffSites
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

CLINIC = UUID(int=10)
SITE = UUID(int=20)
STAFF = UUID(int=30)
CREATED = datetime(2026, 11, 1, 8, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def make_site(name: str = "Sede Norte") -> Site:
    return Site.create(
        site_id=SITE,
        clinic_id=CLINIC,
        name=name,
        clinic_is_demo=True,
        at=CREATED,
    )


def test_create_trims_the_name_and_stamps_both_dates() -> None:
    site = make_site("  Sede Norte  ")

    assert site.name == "Sede Norte"
    assert site.created_at == CREATED
    assert site.updated_at == CREATED
    assert site.clinic_is_demo is True


@pytest.mark.parametrize("name", ["", "   "])
def test_create_rejects_a_blank_name(name: str) -> None:
    with pytest.raises(InsumapError) as error:
        make_site(name)

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.detail == {"errors": [{"field": "body.name", "type": "blank"}]}


def test_create_rejects_a_name_over_the_limit() -> None:
    too_long = "x" * (FieldLimits.SITE_NAME_MAX_LENGTH + 1)

    with pytest.raises(InsumapError) as error:
        make_site(too_long)

    assert error.value.detail == {
        "errors": [{"field": "body.name", "type": "too_long"}]
    }


def test_rename_changes_the_name_and_only_the_update_date() -> None:
    renamed = make_site().renamed(" Sede Sur ", at=LATER)

    assert renamed.name == "Sede Sur"
    assert renamed.created_at == CREATED
    assert renamed.updated_at == LATER
    assert renamed.site_id == SITE


def test_replacing_sites_returns_only_the_links_that_change() -> None:
    kept, dropped, new = UUID(int=1), UUID(int=2), UUID(int=3)
    staff = StaffSites(
        user_id=STAFF,
        clinic_id=CLINIC,
        clinic_is_demo=True,
        site_ids=frozenset({kept, dropped}),
    )

    change = staff.change_to(frozenset({kept, new}), at=LATER)

    assert change.added == frozenset({new})
    assert change.removed == frozenset({dropped})
    assert change.user_id == STAFF
    assert change.clinic_id == CLINIC
    assert change.at == LATER


def test_an_empty_replacement_removes_every_site() -> None:
    staff = StaffSites(
        user_id=STAFF,
        clinic_id=CLINIC,
        clinic_is_demo=False,
        site_ids=frozenset({UUID(int=1)}),
    )

    change = staff.change_to(frozenset(), at=LATER)

    assert change.added == frozenset()
    assert change.removed == frozenset({UUID(int=1)})
    assert staff.with_sites(frozenset()).site_ids == frozenset()
