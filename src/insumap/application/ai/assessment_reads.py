"""Reads of the stored AI outputs: pattern findings, dropout risk and evaluations.

Nothing here calls the AI: these endpoints list what the system stored. Producers
of findings and dropout rows (the nightly triage, RF-74) are not in the backend yet,
so the lists are empty until they run (API.md 9.1).
"""

from __future__ import annotations

from typing import final
from uuid import UUID

from insumap.application.access.ports import DataResource
from insumap.application.ai.records import (
    AiEvaluationFilter,
    AiEvaluationReadPort,
    AiEvaluationView,
    DropoutRiskReadPort,
    DropoutRiskView,
    PatternFindingReadPort,
    PatternFindingView,
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
    """``GET /dropout-risks`` for the doctor's assigned patients (IA7).

    The clinic admin list needs the definer function ``ai.dropout_risk_list()``,
    which the migrations do not have yet, so only the doctor path is served. Row
    level security would show the admin an empty list, so the admin is refused.
    """

    def __init__(self, *, uow: UnitOfWorkPort, dropout: DropoutRiskReadPort) -> None:
        self._uow = uow
        self._dropout = dropout

    def execute(
        self, actor: Actor, *, tier: RiskTier | None, page: PageRequest
    ) -> Page[DropoutRiskView]:
        """The latest dropout assessment per assigned patient, without clinical
        values."""
        actor.require(PermissionCode.AI_DROPOUT_RISK_READ)
        if actor.role is not Role.DOCTOR:
            raise PermissionDeniedError
        with self._uow.begin(TransactionContext.for_actor(actor)):
            return self._dropout.list_for_doctor(actor.user_id, tier=tier, page=page)


@final
class ListAiEvaluationsUseCase:
    """``GET /ai-evaluations``: the clinic's evaluations (RLS), not the platform ones.

    The platform list needs the definer function ``ai.platform_ai_evaluations()``,
    which is not in the migrations yet, so a platform admin is refused.
    """

    def __init__(
        self, *, uow: UnitOfWorkPort, evaluations: AiEvaluationReadPort
    ) -> None:
        self._uow = uow
        self._evaluations = evaluations

    def execute(
        self, actor: Actor, *, filters: AiEvaluationFilter, page: PageRequest
    ) -> Page[AiEvaluationView]:
        """Aggregated metrics only; never series of patients."""
        actor.require(PermissionCode.AI_EVALUATIONS_READ)
        if actor.clinic_id is None:
            raise PermissionDeniedError
        with self._uow.begin(TransactionContext.for_actor(actor)):
            return self._evaluations.list(filters, page)
