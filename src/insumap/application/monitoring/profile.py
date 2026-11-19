"""The own patient profile: account state, clinic and the target profile in force."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWorkPort,
)
from insumap.application.identity.ports import UserRepositoryPort
from insumap.application.metrics.ports import TargetProfilePort
from insumap.application.monitoring.gate import OwnPatientGate
from insumap.domain.identity.account_state import AccountStatus
from insumap.domain.identity.errors import SessionRevokedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.metrics.target_profile import TargetProfile


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class OwnPatientProfile:
    patient_id: UUID
    account_status: AccountStatus
    clinic_name: str
    simulated: bool
    target_profile: TargetProfile | None


@final
class GetOwnPatientProfileUseCase:
    """``GET /patients/own``: who the patient is for the app, without clinical data."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        users: UserRepositoryPort,
        targets: TargetProfilePort,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._users = users
        self._targets = targets

    def execute(self, actor: Actor) -> OwnPatientProfile:
        """The profile of the patient of the token."""
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            scope = self._gate.enter(actor, PermissionCode.PATIENTS_READ_OWN)
            account = self._users.get(actor.user_id)
            if account is None or account.clinic is None:
                raise SessionRevokedError
            found = self._targets.for_patient(scope.patient_id)
            uow.commit()  # keeps the audit row of the read (P09)
        return OwnPatientProfile(
            patient_id=scope.patient_id,
            account_status=account.status,
            clinic_name=account.clinic.name,
            simulated=account.clinic.is_demo,
            target_profile=None if found is None else found.profile,
        )
