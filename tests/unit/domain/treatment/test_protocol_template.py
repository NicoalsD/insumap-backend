"""P05 Prototype: ProtocolTemplate.clone_for_patient() and the template lifecycle."""

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest

from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.treatment.content import ItemType
from insumap.domain.treatment.plan import PlanStatus
from insumap.domain.treatment.template import (
    ProtocolTemplate,
    TemplateStatus,
    derive_template_code,
)
from tests.unit.domain.treatment.factories import (
    AT,
    CLINIC,
    DOCTOR,
    PATIENT,
    TARGET,
    TEMPLATE,
    insulin,
    measure,
    template_content,
    uid,
)

MAX_CODE = 40


def template(status: TemplateStatus = TemplateStatus.ACTIVE) -> ProtocolTemplate:
    return ProtocolTemplate(
        template_id=TEMPLATE,
        clinic_id=CLINIC,
        code="BASAL_BOLO",
        name="Basal-bolo adulto",
        version=2,
        status=status,
        content=template_content(insulin("Basal"), measure()),
        created_by=DOCTOR,
        created_at=AT,
    )


def clone(source: ProtocolTemplate, *, item_ids=None):
    ids = item_ids or (uid(1), uid(2))
    return source.clone_for_patient(
        plan_id=UUID(int=500),
        clinic_id=CLINIC,
        patient_id=PATIENT,
        target_profile_id=TARGET,
        version=1,
        item_ids=ids,
        created_by=DOCTOR,
        at=AT,
    )


def test_the_clone_is_a_draft_that_points_back_to_the_template() -> None:
    plan = clone(template())

    assert plan.status is PlanStatus.DRAFT
    assert plan.version == 1
    assert plan.template_id == TEMPLATE
    assert plan.patient_id == PATIENT
    assert plan.target_profile_id == TARGET
    assert plan.previous_plan_id is None


def test_the_clone_copies_every_item_under_its_own_identifier() -> None:
    source = template()

    plan = clone(source)

    assert [item.name for item in plan.items] == ["Basal", "Glucometría"]
    assert [item.item_id for item in plan.items] == [uid(1), uid(2)]
    assert plan.items[0].item_type is ItemType.INSULIN
    assert plan.items[0].dose_units == Decimal("10")
    assert plan.titration_rules == source.content.titration_rules


def test_the_template_itself_is_not_changed_by_a_clone() -> None:
    source = template()
    before = source

    clone(source)

    assert source == before


def test_a_clone_needs_one_identifier_per_item() -> None:
    with pytest.raises(ValueError, match="one new identifier per item"):
        clone(template(), item_ids=(uid(1),))


def test_a_retired_template_cannot_be_cloned() -> None:
    with pytest.raises(InvalidStateTransitionError):
        clone(template(TemplateStatus.RETIRED))


def test_a_new_version_is_active_and_keeps_the_family() -> None:
    source = template()
    new_content = template_content(insulin("Basal ajustada", units="12"))

    newer = source.new_version(
        template_id=UUID(int=600),
        version=3,
        content=new_content,
        created_by=DOCTOR,
        at=AT,
    )

    assert newer.version == 3
    assert newer.code == source.code
    assert newer.name == source.name
    assert newer.status is TemplateStatus.ACTIVE
    assert newer.content == new_content
    assert source.version == 2


def test_retiring_moves_active_to_retired_and_only_once() -> None:
    retired = template().retired()

    assert retired.status is TemplateStatus.RETIRED
    with pytest.raises(InvalidStateTransitionError):
        retired.retired()
    with pytest.raises(InvalidStateTransitionError):
        retired.new_version(
            template_id=UUID(int=601),
            version=3,
            content=template().content,
            created_by=DOCTOR,
            at=AT,
        )


def test_the_code_is_ascii_upper_case_and_starts_with_a_letter() -> None:
    assert derive_template_code("Basal-bolo adulto DM1", max_length=MAX_CODE) == (
        "BASAL_BOLO_ADULTO_DM1"
    )
    assert derive_template_code("Diabetes gestación", max_length=MAX_CODE) == (
        "DIABETES_GESTACION"
    )
    assert derive_template_code("2 dosis al día", max_length=MAX_CODE) == (
        "P_2_DOSIS_AL_DIA"
    )
    assert derive_template_code("¡¡¡", max_length=MAX_CODE) == "PROTOCOL"


def test_the_code_fits_the_column_and_has_no_trailing_underscore() -> None:
    long_name = "x" * 39 + " y"

    code = derive_template_code(long_name, max_length=MAX_CODE)

    assert len(code) <= MAX_CODE
    assert not code.endswith("_")


def test_the_clone_belongs_to_the_patient_clinic_not_to_a_global_seed() -> None:
    replaced = replace(template(), clinic_id=None)

    plan = clone(replaced)

    assert plan.clinic_id == CLINIC
