"""``GET /follow-ups``: the controls of an assigned patient, or the patient's own."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.patient_scope import PatientScope
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.follow_ups.ports import FollowUpRepositoryPort
from insumap.domain.follow_ups.follow_up import FollowUp, FollowUpStatus
from insumap.domain.identity.permissions import PermissionCode


@dataclass(frozen=True, slots=True, kw_only=True)
class ListFollowUpsInput:
    """The caller, the patient (doctors only), an optional status and the page."""

    actor: Actor
    patient_id: UUID | None
    status: FollowUpStatus | None
    page: PageRequest


@final
class ListFollowUpsUseCase:
    """Controls of one patient; the doctor's reads are audited, the patient's not."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        scope: PatientScope,
        follow_ups: FollowUpRepositoryPort,
    ) -> None:
        self._uow = uow
        self._scope = scope
        self._follow_ups = follow_ups

    def execute(self, input: ListFollowUpsInput) -> Page[FollowUp]:
        """A page of controls, newest first; the read is committed for its audit row."""
        actor = input.actor
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            patient_id = self._scope.enter(
                actor,
                input.patient_id,
                staff_permission=PermissionCode.FOLLOW_UPS_MANAGE,
                own_permission=PermissionCode.FOLLOW_UPS_READ_OWN,
                resource=DataResource.TREATMENT_PLAN,
            )
            page = self._follow_ups.list_for_patient(
                patient_id, status=input.status, page=input.page
            )
            unit.commit()
        return page
