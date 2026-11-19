"""``GET /patients`` and ``GET /patients/{patient_id}``: the administrator's view.

Only ``patients.read_roster`` (``CLINIC_ADMIN``) reads them. Each read writes its
row in ``audit.data_access_log`` (P09) in the transaction of the read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessLogPort,
    DataAccessOutcome,
    DataAccessRecord,
    DataResource,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.patients.ports import (
    PatientAdministrativeView,
    PatientRosterFilter,
    PatientRosterPort,
)
from insumap.application.users.access import clinic_of
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.identity.permissions import PermissionCode
from insumap.shared.request_context import current_request_id
from insumap.shared.time import Clock

ROSTER_PURPOSE: Final = AccessPurpose.ADMINISTRATION


@dataclass(frozen=True, slots=True, kw_only=True)
class ListPatientsInput:
    """The caller, the optional filters and the page asked for."""

    actor: Actor
    filters: PatientRosterFilter
    page: PageRequest


@final
class ListPatientsUseCase:
    """A page of the patients of the caller's clinic, without clinical data."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        roster: PatientRosterPort,
        access_log: DataAccessLogPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._roster = roster
        self._log = access_log
        self._clock = clock

    def execute(self, input: ListPatientsInput) -> Page[PatientAdministrativeView]:
        """Only ``patients.read_roster``; the clinic comes from the token."""
        actor = input.actor
        actor.require(PermissionCode.PATIENTS_READ_ROSTER)
        clinic_id = clinic_of(actor)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            page = self._roster.list(clinic_id, input.filters, input.page)
            self._log.record_granted(
                _entry(
                    self._clock,
                    actor,
                    patient_id=None,
                    resource=DataResource.PATIENT_LIST,
                    outcome=DataAccessOutcome.GRANTED,
                )
            )
        return page


@dataclass(frozen=True, slots=True, kw_only=True)
class GetPatientInput:
    """The caller and the patient asked for."""

    actor: Actor
    patient_id: UUID


@final
class GetPatientUseCase:
    """One patient of the caller's clinic; anyone else is ``404``, as if missing."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        roster: PatientRosterPort,
        access_log: DataAccessLogPort,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._roster = roster
        self._log = access_log
        self._clock = clock

    def execute(self, input: GetPatientInput) -> PatientAdministrativeView:
        """Only ``patients.read_roster``; a denied id leaves a ``DENIED`` row."""
        actor = input.actor
        actor.require(PermissionCode.PATIENTS_READ_ROSTER)
        clinic_id = clinic_of(actor)
        with self._uow.begin(TransactionContext.for_actor(actor)):
            view = self._roster.get(clinic_id, input.patient_id)
            if view is None:
                self._log.record_denied(
                    _entry(
                        self._clock,
                        actor,
                        patient_id=input.patient_id,
                        resource=DataResource.PATIENT_DEMOGRAPHICS,
                        outcome=DataAccessOutcome.DENIED,
                    )
                )
                raise ResourceNotFoundError
            self._log.record_granted(
                _entry(
                    self._clock,
                    actor,
                    patient_id=input.patient_id,
                    resource=DataResource.PATIENT_DEMOGRAPHICS,
                    outcome=DataAccessOutcome.GRANTED,
                )
            )
        return view


def _entry(
    clock: Clock,
    actor: Actor,
    *,
    patient_id: UUID | None,
    resource: DataResource,
    outcome: DataAccessOutcome,
) -> DataAccessRecord:
    return DataAccessRecord(
        occurred_at=clock.now(),
        clinic_id=actor.clinic_id,
        actor_user_id=actor.user_id,
        actor_role=actor.role,
        patient_id=patient_id,
        resource=resource,
        purpose=ROSTER_PURPOSE,
        outcome=outcome,
        request_id=current_request_id(),
    )
