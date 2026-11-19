"""Reads of the treatment plans and protocol templates (API.md 8.7).

Each read opens its transaction with the RLS context of the actor. A plan or a
patient the session may not see answers ``404``, and a read of clinical data
leaves its ``audit.data_access_log`` row inside that transaction (P09 over P11).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.monitoring.gate import AssignedPatientGate, OwnPatientGate
from insumap.application.treatment.ports import (
    ProtocolTemplateRepositoryPort,
    StoredSnapshot,
    TreatmentPlanRepositoryPort,
    TreatmentPlanSnapshotPort,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.treatment.plan import PlanStatus, TreatmentPlan
from insumap.domain.treatment.template import ProtocolTemplate, TemplateStatus


def _committed[T](uow: UnitOfWorkPort, actor: Actor, read: Callable[[], T]) -> T:
    """Run a read and commit it.

    A transaction that is not committed is rolled back, and so is the audit row
    of a granted read (P09 writes it in the same transaction). Committing after
    the read keeps the audit row, and it is written before the response.
    """
    with uow.begin(TransactionContext.for_actor(actor)) as unit:
        result = read()
        unit.commit()
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class ProtocolTemplateView:
    """A template as read: the version asked for and the versions of its family."""

    template: ProtocolTemplate
    versions: tuple[ProtocolTemplate, ...]


@final
class ListProtocolTemplatesUseCase:
    """``GET /protocol-templates``: the latest version of each template."""

    def __init__(
        self, *, uow: UnitOfWorkPort, templates: ProtocolTemplateRepositoryPort
    ):
        self._uow = uow
        self._templates = templates

    def execute(
        self, actor: Actor, status: TemplateStatus | None, page: PageRequest
    ) -> Page[ProtocolTemplate]:
        actor.require(PermissionCode.PROTOCOL_TEMPLATES_READ)
        return _committed(
            self._uow, actor, lambda: self._templates.list_latest(status, page)
        )


@final
class GetProtocolTemplateUseCase:
    """``GET /protocol-templates/{template_id}``: one version and its family."""

    def __init__(
        self, *, uow: UnitOfWorkPort, templates: ProtocolTemplateRepositoryPort
    ):
        self._uow = uow
        self._templates = templates

    def execute(self, actor: Actor, template_id: UUID) -> ProtocolTemplateView:
        actor.require(PermissionCode.PROTOCOL_TEMPLATES_READ)

        def read() -> ProtocolTemplateView:
            template = self._templates.get(template_id)
            if template is None:
                raise ResourceNotFoundError
            family = self._templates.family(template.clinic_id, template.code)
            return ProtocolTemplateView(template=template, versions=family)

        return _committed(self._uow, actor, read)


@final
class ListTreatmentPlansUseCase:
    """``GET /treatment-plans``: the plans of one assigned patient."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: AssignedPatientGate,
        plans: TreatmentPlanRepositoryPort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._plans = plans

    def execute(
        self,
        actor: Actor,
        patient_id: UUID,
        status: PlanStatus | None,
        page: PageRequest,
    ) -> Page[TreatmentPlan]:
        actor.require(PermissionCode.TREATMENT_PLANS_MANAGE)

        def read() -> Page[TreatmentPlan]:
            patient = self._gate.enter(
                actor,
                PermissionCode.TREATMENT_PLANS_MANAGE,
                patient_id,
                DataResource.TREATMENT_PLAN,
            )
            return self._plans.list_for_patient(patient, status, page)

        return _committed(self._uow, actor, read)


@final
class GetTreatmentPlanUseCase:
    """``GET /treatment-plans/{plan_id}``: one plan of an assigned patient."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: AssignedPatientGate,
        plans: TreatmentPlanRepositoryPort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._plans = plans

    def execute(self, actor: Actor, plan_id: UUID) -> TreatmentPlan:
        actor.require(PermissionCode.TREATMENT_PLANS_MANAGE)

        def read() -> TreatmentPlan:
            plan = self._plans.get(plan_id)
            if plan is None:
                raise ResourceNotFoundError
            self._gate.enter(
                actor,
                PermissionCode.TREATMENT_PLANS_MANAGE,
                plan.patient_id,
                DataResource.TREATMENT_PLAN,
            )
            return plan

        return _committed(self._uow, actor, read)


@final
class ListTreatmentPlanSnapshotsUseCase:
    """``GET /treatment-plans/{plan_id}/snapshots``: the photos kept for a plan."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: AssignedPatientGate,
        plans: TreatmentPlanRepositoryPort,
        snapshots: TreatmentPlanSnapshotPort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._plans = plans
        self._snapshots = snapshots

    def execute(
        self, actor: Actor, plan_id: UUID, page: PageRequest
    ) -> Page[StoredSnapshot]:
        actor.require(PermissionCode.TREATMENT_PLANS_MANAGE)

        def read() -> Page[StoredSnapshot]:
            plan = self._plans.get(plan_id)
            if plan is None:
                raise ResourceNotFoundError
            self._gate.enter(
                actor,
                PermissionCode.TREATMENT_PLANS_MANAGE,
                plan.patient_id,
                DataResource.TREATMENT_PLAN,
            )
            return self._snapshots.list_for_plan(plan.plan_id, page)

        return _committed(self._uow, actor, read)


@final
class GetOwnTreatmentPlanUseCase:
    """``GET /patients/own/treatment-plan``: the active plan of the patient himself.

    Only the active plan is returned: a draft is never shown to the patient.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        plans: TreatmentPlanRepositoryPort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._plans = plans

    def execute(self, actor: Actor) -> TreatmentPlan:
        def read() -> TreatmentPlan:
            scope = self._gate.enter(actor, PermissionCode.TREATMENT_PLANS_READ_OWN)
            plan = self._plans.active_for(scope.patient_id)
            if plan is None:
                raise ResourceNotFoundError
            return plan

        return _committed(self._uow, actor, read)
