"""Reads of plans and templates: the patient sees only his active plan (C3, P11)."""

from dataclasses import replace
from uuid import UUID

import pytest

from insumap.application.access.ports import AccessPurpose, DataResource
from insumap.application.common.pagination import PageRequest
from insumap.application.treatment.queries import (
    GetOwnTreatmentPlanUseCase,
    GetProtocolTemplateUseCase,
    GetTreatmentPlanUseCase,
    ListTreatmentPlansUseCase,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.errors import ConsentRequiredError
from insumap.domain.treatment.plan import PlanStatus
from tests.support.treatment_fakes import active
from tests.unit.application.treatment.helpers import (
    World,
    doctor,
    patient_actor,
    template_row,
)
from tests.unit.domain.treatment.factories import (
    DOCTOR,
    PATIENT,
    TEMPLATE,
    draft,
    insulin,
    measure,
    plan_items,
)

PAGE = PageRequest(limit=20)
DRAFT_PLAN = UUID(int=31)
ACTIVE_PLAN = UUID(int=32)


def plan(plan_id: UUID, *, is_active: bool):
    base = replace(draft(*plan_items(insulin(), measure())), plan_id=plan_id)
    return active(base) if is_active else base


def test_the_patient_reads_his_active_plan_and_never_a_draft() -> None:
    world = World(
        plans=(plan(DRAFT_PLAN, is_active=False), plan(ACTIVE_PLAN, is_active=True))
    )

    own = GetOwnTreatmentPlanUseCase(
        uow=world.uow, gate=world.own_gate, plans=world.plans
    ).execute(patient_actor())

    assert own.plan_id == ACTIVE_PLAN
    assert own.status is PlanStatus.ACTIVE


def test_without_an_active_plan_the_patient_gets_not_found() -> None:
    world = World(plans=(plan(DRAFT_PLAN, is_active=False),))

    with pytest.raises(ResourceNotFoundError):
        GetOwnTreatmentPlanUseCase(
            uow=world.uow, gate=world.own_gate, plans=world.plans
        ).execute(patient_actor())


def test_the_patient_without_accepted_consent_is_refused() -> None:
    world = World(plans=(plan(ACTIVE_PLAN, is_active=True),), accepted=False)

    with pytest.raises(ConsentRequiredError):
        GetOwnTreatmentPlanUseCase(
            uow=world.uow, gate=world.own_gate, plans=world.plans
        ).execute(patient_actor())


def test_the_doctor_reads_a_plan_of_an_assigned_patient_and_it_is_audited() -> None:
    world = World(plans=(plan(ACTIVE_PLAN, is_active=True),))

    found = GetTreatmentPlanUseCase(
        uow=world.uow, gate=world.gate, plans=world.plans
    ).execute(doctor(), ACTIVE_PLAN)

    assert found.plan_id == ACTIVE_PLAN
    assert world.assignments.reads == [
        (DOCTOR, PATIENT, AccessPurpose.CARE, DataResource.TREATMENT_PLAN)
    ]


def test_a_plan_of_an_unassigned_patient_is_not_found() -> None:
    world = World(plans=(plan(ACTIVE_PLAN, is_active=True),), assigned=())

    with pytest.raises(ResourceNotFoundError):
        GetTreatmentPlanUseCase(
            uow=world.uow, gate=world.gate, plans=world.plans
        ).execute(doctor(), ACTIVE_PLAN)


def test_listing_the_plans_of_a_patient_reads_through_the_gate() -> None:
    world = World(plans=(plan(ACTIVE_PLAN, is_active=True),))

    page = ListTreatmentPlansUseCase(
        uow=world.uow, gate=world.gate, plans=world.plans
    ).execute(doctor(), PATIENT, None, PAGE)

    assert [row.plan_id for row in page.items] == [ACTIVE_PLAN]
    assert world.assignments.reads[-1][3] is DataResource.TREATMENT_PLAN


def test_a_template_read_returns_its_family() -> None:
    world = World(
        templates=(
            template_row(version=1),
            template_row(template_id=UUID(int=22), version=2),
        )
    )

    view = GetProtocolTemplateUseCase(uow=world.uow, templates=world.templates).execute(
        doctor(), TEMPLATE
    )

    assert view.template.template_id == TEMPLATE
    assert [row.version for row in view.versions] == [1, 2]
