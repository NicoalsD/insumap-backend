"""Ports of the treatment plans: repositories under row level security."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.treatment.plan import (
    PlanStatus,
    TreatmentPlan,
    TreatmentPlanMemento,
)
from insumap.domain.treatment.template import ProtocolTemplate, TemplateStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredSnapshot:
    """A memento as it was stored: where it belongs and who took it."""

    snapshot_id: UUID
    plan_id: UUID
    number: int
    memento: TreatmentPlanMemento
    taken_by: UUID


class ProtocolTemplateRepositoryPort(ABC):
    """``care.protocol_templates``: a clinic's templates and the global seeds."""

    @abstractmethod
    def get(self, template_id: UUID) -> ProtocolTemplate | None:
        """One template version, or ``None`` if the session cannot see it."""

    @abstractmethod
    def family(self, clinic_id: UUID | None, code: str) -> tuple[ProtocolTemplate, ...]:
        """Every version of a template of the same owner, oldest first."""

    @abstractmethod
    def insert(self, template: ProtocolTemplate) -> None:
        """Write a new template version."""

    @abstractmethod
    def retire(self, template: ProtocolTemplate) -> None:
        """Write the change of an ``ACTIVE`` version to ``RETIRED``."""

    @abstractmethod
    def list_latest(
        self, status: TemplateStatus | None, page: PageRequest
    ) -> Page[ProtocolTemplate]:
        """The latest version of each template the session sees, by identifier."""


class TreatmentPlanRepositoryPort(ABC):
    """``care.treatment_plans`` and ``care.treatment_plan_items``."""

    @abstractmethod
    def get(self, plan_id: UUID) -> TreatmentPlan | None:
        """One plan with its items, or ``None`` if the session cannot see it."""

    @abstractmethod
    def active_for(self, patient_id: UUID) -> TreatmentPlan | None:
        """The active plan of a patient, if there is one."""

    @abstractmethod
    def highest_version(self, patient_id: UUID) -> int:
        """The highest version of any plan of the patient (0 when none)."""

    @abstractmethod
    def insert(self, plan: TreatmentPlan) -> None:
        """Write a new plan and its items."""

    @abstractmethod
    def update(self, plan: TreatmentPlan) -> None:
        """Write the header of a plan (status, dates, notes, rules, lock)."""

    @abstractmethod
    def replace_items(self, plan: TreatmentPlan) -> None:
        """Replace the items of a draft with those of ``plan``."""

    @abstractmethod
    def list_for_patient(
        self, patient_id: UUID, status: PlanStatus | None, page: PageRequest
    ) -> Page[TreatmentPlan]:
        """The plans of a patient, newest first."""


class TreatmentPlanSnapshotPort(ABC):
    """``care.treatment_plan_snapshots``: append-only photos of a plan (P16)."""

    @abstractmethod
    def next_number(self, plan_id: UUID) -> int:
        """The number of the next photo of a plan."""

    @abstractmethod
    def append(
        self,
        *,
        plan_id: UUID,
        number: int,
        memento: TreatmentPlanMemento,
        taken_by: UUID,
    ) -> None:
        """Keep a photo; photos are never changed or removed."""

    @abstractmethod
    def get(self, snapshot_id: UUID, plan_id: UUID) -> StoredSnapshot | None:
        """A photo of the plan, or ``None`` (a photo of another plan is ``None``)."""

    @abstractmethod
    def list_for_plan(self, plan_id: UUID, page: PageRequest) -> Page[StoredSnapshot]:
        """The photos of a plan, oldest first."""


class TargetProfileLookupPort(ABC):
    """The goals profile a new plan is built with."""

    @abstractmethod
    def profile_id_for(self, patient_id: UUID) -> UUID | None:
        """The patient profile, else the default one; ``None`` if there is none."""
