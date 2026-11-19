"""``GET /patients/own/injection-sites``: where the next injection goes.

The answer is a place, never an amount: nothing here reads or returns a dose.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import final
from uuid import UUID

from insumap.application.common.actor import Actor
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWorkPort,
)
from insumap.application.monitoring.gate import OwnPatientGate
from insumap.application.treatment.ports import TreatmentPlanRepositoryPort
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.injection_rule import (
    LIPOHYPERTROPHY_LOOKBACK,
    InjectionHistoryEntry,
    InjectionPatientProfile,
    InjectionRuleInput,
    InjectionSites,
    InjectionSiteStrategy,
    LipohypertrophyReport,
    plan_sites_for,
)
from insumap.domain.monitoring.injection_sites import PregnancyStatus, SiteCode
from insumap.domain.monitoring.records import InsulinKind
from insumap.domain.onboarding.vocabulary import Sex
from insumap.domain.treatment.content import ItemType
from insumap.domain.treatment.plan import TreatmentPlan
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.time import Clock


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PatientBodyProfile:
    """The fields of ``clinic.patients`` the injection rule reads."""

    sex: Sex
    birth_date: date
    bmi: Decimal | None
    pregnancy_status: PregnancyStatus


class PatientBodyProfilePort(ABC):
    """``clinic.patients``: sex, birth date, BMI and pregnancy status."""

    @abstractmethod
    def for_patient(self, patient_id: UUID) -> PatientBodyProfile | None:
        """The body profile of the patient, or ``None`` if the session cannot see it."""


class InjectionHistoryPort(ABC):
    """What the rule reads from the records: the last doses by site and the reports."""

    @abstractmethod
    def latest_by_site(self, patient_id: UUID) -> Sequence[InjectionHistoryEntry]:
        """The latest current dose of every site and insulin family (at most 16).

        The family is basal or rapid (bolus, correction, mixed). Doses without a
        site, corrected doses and annulled doses are left out.
        """

    @abstractmethod
    def lipohypertrophy_since(
        self, patient_id: UUID, since: datetime
    ) -> Sequence[LipohypertrophyReport]:
        """Current lipohypertrophy symptoms with a site, from ``since`` on."""


def sites_allowed_by_plan(
    plan: TreatmentPlan | None, kind: InsulinKind
) -> tuple[SiteCode, ...] | None:
    """Sites the active plan allows for ``kind``; ``None`` when it does not restrict.

    The plan names its insulin classes with its own enum, so they are compared by value.
    """
    if plan is None:
        return None
    return plan_sites_for(
        item.injection_sites
        for item in plan.items
        if item.item_type is ItemType.INSULIN
        and item.insulin_kind is not None
        and item.insulin_kind.value == kind.value
    )


@final
class GetOwnInjectionSitesUseCase:
    """The suggested site of the next dose and the state of the eight sites.

    The rule is a strategy (P19); this use case only gathers its input: the
    profile, the sites the plan allows, the latest doses and the reports.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        gate: OwnPatientGate,
        profiles: PatientBodyProfilePort,
        history: InjectionHistoryPort,
        plans: TreatmentPlanRepositoryPort,
        strategy: InjectionSiteStrategy,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._gate = gate
        self._profiles = profiles
        self._history = history
        self._plans = plans
        self._strategy = strategy
        self._clock = clock

    def execute(self, actor: Actor, kind: InsulinKind) -> InjectionSites:
        """The answer for the patient of the token (C3 applies)."""
        now = self._clock.now()
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            scope = self._gate.enter(actor, PermissionCode.RECORDS_READ_OWN)
            body = self._profiles.for_patient(scope.patient_id)
            if body is None:
                raise InsumapError(ErrorCode.NOT_FOUND)
            reports = self._history.lipohypertrophy_since(
                scope.patient_id, now - LIPOHYPERTROPHY_LOOKBACK
            )
            answer = self._strategy.suggest(
                InjectionRuleInput(
                    kind=kind,
                    now=now,
                    profile=InjectionPatientProfile(
                        sex=body.sex,
                        birth_date=body.birth_date,
                        bmi=body.bmi,
                        pregnancy=body.pregnancy_status,
                        lipohypertrophy=tuple(reports),
                    ),
                    plan=sites_allowed_by_plan(
                        self._plans.active_for(scope.patient_id), kind
                    ),
                    history=tuple(self._history.latest_by_site(scope.patient_id)),
                )
            )
            uow.commit()
        return answer
