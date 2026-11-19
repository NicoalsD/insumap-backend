"""Reads of the stored AI outputs: pattern findings, dropout risk and evaluations.

Nothing here calls the AI: these endpoints list what the system stored. Producers
of findings and dropout rows (the nightly triage, RF-74) are not in the backend yet,
so the lists are empty until they run (API.md 9.1).

The administrators do not read ``ai`` rows under RLS: the clinic administrator's
dropout list and the platform's evaluations come from definer functions.
"""

from __future__ import annotations

from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.ai.records import (
    AiEvaluationFilter,
    AiEvaluationReadPort,
    AiEvaluationView,
    DropoutRiskClinicReadPort,
    DropoutRiskReadPort,
    DropoutRiskView,
    PatternFindingReadPort,
    PatternFindingView,
    PlatformAiEvaluationReadPort,
)
from insumap.application.common.actor import Actor
from insumap.application.common.pagination import Page, PageRequest
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.monitoring.gate import AssignedPatientGate
from insumap.domain.ai.risk import RiskTier
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.roles import Role


@final
class ListPatternFindingsUseCase:
    """``GET /patients/{patient_id}/pattern-findings`` for an assigned patient (IA3)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned_gate: AssignedPatientGate,
        findings: PatternFindingReadPort,
    ) -> None:
        self._uow = uow
        self._assigned = assigned_gate
        self._findings = findings

    def execute(
        self, actor: Actor, patient_id: UUID, page: PageRequest
    ) -> Page[PatternFindingView]:
        """Newest first; the read is audited (P09) before the page is returned."""
        permission = PermissionCode.AI_RISK_READ_ASSIGNED
        actor.require(permission)
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            self._assigned.enter(actor, permission, patient_id, DataResource.AI_OUTPUTS)
            result = self._findings.list_for_patient(patient_id, page)
            unit.commit()  # keeps the audit row of the read (P09)
        return result


@final
class ListDropoutRisksUseCase:
    """``GET /dropout-risks``: the doctor's assigned patients (IA7), or the clinic's
    administrative list for the CLINIC_ADMIN (``ai.dropout_risk_list()``).

    Any other role is refused before a read: the function would refuse it too, but
    as a server error.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        assigned_gate: AssignedPatientGate,
        dropout: DropoutRiskReadPort,
        clinic_dropout: DropoutRiskClinicReadPort,
    ) -> None:
        self._uow = uow
        self._assigned = assigned_gate
        self._dropout = dropout
        self._clinic_dropout = clinic_dropout

    def execute(
        self, actor: Actor, *, tier: RiskTier | None, page: PageRequest
    ) -> Page[DropoutRiskView]:
        """The latest dropout assessment of each patient, audited (P09) for doctors."""
        permission = PermissionCode.AI_DROPOUT_RISK_READ
        actor.require(permission)
        if actor.role is Role.CLINIC_ADMIN and actor.clinic_id is not None:
            with self._uow.begin(TransactionContext.for_actor(actor)):
                return self._clinic_dropout.list_for_clinic(tier=tier, page=page)
        if actor.role is not Role.DOCTOR:
            raise PermissionDeniedError
        with self._uow.begin(TransactionContext.for_actor(actor)) as unit:
            result = self._dropout.list_for_doctor(actor.user_id, tier=tier, page=page)
            for patient in sorted({item.patient_id for item in result.items}, key=str):
                self._assigned.enter(
                    actor, permission, patient, DataResource.AI_OUTPUTS
                )
            unit.commit()  # keeps the audit rows of the reads (P09)
        return result


@final
class ListAiEvaluationsUseCase:
    """``GET /ai-evaluations``: the clinic's evaluations under RLS, or every clinic's
    for the PLATFORM_ADMIN through ``ai.platform_ai_evaluations()``.

    The clinic policy already lets the CLINIC_ADMIN read its clinic's rows and the
    global ones (``clinic_id`` NULL), so that path needs no function.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        evaluations: AiEvaluationReadPort,
        platform: PlatformAiEvaluationReadPort,
    ) -> None:
        self._uow = uow
        self._evaluations = evaluations
        self._platform = platform

    def execute(
        self, actor: Actor, *, filters: AiEvaluationFilter, page: PageRequest
    ) -> Page[AiEvaluationView]:
        """Aggregated metrics only; never series of patients."""
        actor.require(PermissionCode.AI_EVALUATIONS_READ)
        if actor.role is Role.PLATFORM_ADMIN:
            with self._uow.begin(TransactionContext.for_actor(actor)):
                return self._platform.list(filters, page)
        if actor.clinic_id is None:
            raise PermissionDeniedError
        with self._uow.begin(TransactionContext.for_actor(actor)):
            return self._evaluations.list(filters, page)
