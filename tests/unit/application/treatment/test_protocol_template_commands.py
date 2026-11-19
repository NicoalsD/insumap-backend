"""Template decisions: create, version and retire, owned by the clinic (P05, P09)."""

from uuid import UUID

import pytest

from insumap.application.treatment.template_commands import (
    CreateProtocolTemplateCommand,
    CreateProtocolTemplateVersionCommand,
    RetireProtocolTemplateCommand,
)
from insumap.domain.common.errors import ConflictError, ResourceNotFoundError
from insumap.domain.identity.errors import (
    InvalidStateTransitionError,
    PermissionDeniedError,
)
from insumap.domain.treatment.content import TemplateContent
from insumap.domain.treatment.template import TemplateStatus
from tests.unit.application.treatment.helpers import World, admin, doctor, template_row
from tests.unit.domain.treatment.factories import TEMPLATE, insulin, template_content

NEW_CONTENT: TemplateContent = template_content(insulin("Basal nueva", units="6"))


def test_creating_a_template_derives_its_code_and_stores_version_one() -> None:
    world = World()

    created = world.create_template.handle(
        CreateProtocolTemplateCommand(
            actor=admin(), name="Basal-bolo adulto DM1", content=NEW_CONTENT
        )
    )

    assert created.code == "BASAL_BOLO_ADULTO_DM1"
    assert created.version == 1
    assert created.status is TemplateStatus.ACTIVE
    assert created.clinic_id is not None
    assert created.content == NEW_CONTENT


def test_a_name_that_derives_an_existing_code_is_a_conflict() -> None:
    world = World(templates=(template_row(code="BASAL_BOLO"),))

    with pytest.raises(ConflictError):
        world.create_template.handle(
            CreateProtocolTemplateCommand(
                actor=admin(), name="basal bolo", content=NEW_CONTENT
            )
        )


def test_the_doctor_cannot_manage_templates() -> None:
    world = World()

    with pytest.raises(PermissionDeniedError):
        world.create_template.handle(
            CreateProtocolTemplateCommand(
                actor=doctor(), name="Nueva", content=NEW_CONTENT
            )
        )


def test_a_new_version_follows_the_latest_and_keeps_the_others() -> None:
    world = World(
        templates=(
            template_row(version=1),
            template_row(template_id=UUID(int=21), version=2),
        )
    )

    version = world.version_template.handle(
        CreateProtocolTemplateVersionCommand(
            actor=admin(), template_id=TEMPLATE, content=NEW_CONTENT
        )
    )

    assert version.version == 3
    assert version.code == "BASAL_BOLO"
    assert world.templates.rows[TEMPLATE].version == 1


def test_a_global_seed_cannot_be_versioned_by_a_clinic() -> None:
    seed = template_row(clinic=None)
    world = World(templates=(seed,))

    with pytest.raises(ResourceNotFoundError):
        world.version_template.handle(
            CreateProtocolTemplateVersionCommand(
                actor=admin(), template_id=TEMPLATE, content=NEW_CONTENT
            )
        )


def test_a_retired_template_cannot_be_versioned() -> None:
    world = World(templates=(template_row(status=TemplateStatus.RETIRED),))

    with pytest.raises(InvalidStateTransitionError):
        world.version_template.handle(
            CreateProtocolTemplateVersionCommand(
                actor=admin(), template_id=TEMPLATE, content=NEW_CONTENT
            )
        )


def test_retiring_retires_every_active_version_of_the_family() -> None:
    world = World(
        templates=(
            template_row(version=1),
            template_row(template_id=UUID(int=21), version=2),
        )
    )

    retired = world.retire_template.handle(
        RetireProtocolTemplateCommand(actor=admin(), template_id=TEMPLATE)
    )

    assert retired.status is TemplateStatus.RETIRED
    assert {row.status for row in world.templates.rows.values()} == {
        TemplateStatus.RETIRED
    }
    assert world.templates.writes == ["retire:1", "retire:2"]


def test_retiring_twice_is_an_invalid_transition() -> None:
    world = World(templates=(template_row(status=TemplateStatus.RETIRED),))

    with pytest.raises(InvalidStateTransitionError):
        world.retire_template.handle(
            RetireProtocolTemplateCommand(actor=admin(), template_id=TEMPLATE)
        )
