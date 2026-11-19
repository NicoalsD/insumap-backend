"""A treatment plan: its content, its versions and its lifecycle.

The plan is an aggregate of plain values. The use cases pass in the identifiers,
the actor and the instant, so nothing here generates ids or reads the clock.

Pattern: P05 Prototype (``copy_for_new_version``) and P16 Memento
(``create_memento`` and ``from_memento``). The builder that validates the
invariants before activation is ``TreatmentPlanBuilder`` (P04).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, final
from uuid import UUID

from insumap.domain.identity.errors import InvalidStateTransitionError
from insumap.domain.treatment.content import PlanItem, TitrationRules
from insumap.domain.treatment.primitives import (
    plan_item_from_primitive,
    plan_item_to_primitive,
    rules_from_primitive,
    rules_to_primitive,
)

MACHINE_NAME: Final = "treatment_plan"
MEMENTO_SCHEMA_VERSION: Final = 1


class PlanStatus(StrEnum):
    """Lifecycle of a plan: a draft becomes active, then superseded."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class TreatmentPlanMemento:
    """Pattern: P16 Memento. A photo of a plan, made of primitives only.

    ``data`` is stored as is in ``care.treatment_plan_snapshots.snapshot``.
    """

    schema_version: int
    taken_at: datetime
    data: dict[str, Any]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class TreatmentPlan:
    """One version of the treatment of a patient.

    Pattern: P05 Prototype (``copy_for_new_version``) and P16 Memento (originator).
    """

    plan_id: UUID
    clinic_id: UUID
    patient_id: UUID
    version: int
    status: PlanStatus
    target_profile_id: UUID
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    items: tuple[PlanItem, ...]
    template_id: UUID | None = None
    previous_plan_id: UUID | None = None
    titration_rules: TitrationRules | None = None
    notes: str | None = None
    activated_by: UUID | None = None
    activated_at: datetime | None = None
    superseded_at: datetime | None = None
    lock_version: int = 0

    @classmethod
    def draft(
        cls,
        *,
        plan_id: UUID,
        clinic_id: UUID,
        patient_id: UUID,
        version: int,
        target_profile_id: UUID,
        created_by: UUID,
        at: datetime,
        items: tuple[PlanItem, ...],
        template_id: UUID | None = None,
        previous_plan_id: UUID | None = None,
        titration_rules: TitrationRules | None = None,
        notes: str | None = None,
    ) -> TreatmentPlan:
        """A new plan in ``DRAFT``; nothing is validated until activation."""
        return cls(
            plan_id=plan_id,
            clinic_id=clinic_id,
            patient_id=patient_id,
            version=version,
            status=PlanStatus.DRAFT,
            target_profile_id=target_profile_id,
            created_by=created_by,
            created_at=at,
            updated_at=at,
            items=items,
            template_id=template_id,
            previous_plan_id=previous_plan_id,
            titration_rules=titration_rules,
            notes=notes,
        )

    @property
    def is_draft(self) -> bool:
        return self.status is PlanStatus.DRAFT

    def with_content(
        self,
        *,
        items: tuple[PlanItem, ...],
        titration_rules: TitrationRules | None,
        notes: str | None,
        at: datetime,
    ) -> TreatmentPlan:
        """Replace the content of a draft; an active plan is never edited."""
        self._require(PlanStatus.DRAFT, "update")
        return replace(
            self,
            items=items,
            titration_rules=titration_rules,
            notes=notes,
            updated_at=at,
            lock_version=self.lock_version + 1,
        )

    def activate(self, *, by: UUID, at: datetime) -> TreatmentPlan:
        """``DRAFT`` to ``ACTIVE``. The caller supersedes the previous active plan."""
        self._require(PlanStatus.DRAFT, "activate")
        return replace(
            self,
            status=PlanStatus.ACTIVE,
            activated_by=by,
            activated_at=at,
            updated_at=at,
            lock_version=self.lock_version + 1,
        )

    def supersede(self, *, at: datetime) -> TreatmentPlan:
        """``ACTIVE`` to ``SUPERSEDED``: the only change an active plan admits."""
        self._require(PlanStatus.ACTIVE, "supersede")
        return replace(
            self,
            status=PlanStatus.SUPERSEDED,
            superseded_at=at,
            updated_at=at,
            lock_version=self.lock_version + 1,
        )

    def copy_for_new_version(
        self,
        *,
        new_plan_id: UUID,
        item_ids: tuple[UUID, ...],
        version: int,
        created_by: UUID,
        at: datetime,
    ) -> TreatmentPlan:
        """P05: a deep copy in ``DRAFT`` with new identifiers; this plan is untouched.

        The new version refers to this plan through ``previous_plan_id``. The
        caller chooses the version number, so the number is unique per patient.
        """
        if len(item_ids) != len(self.items):
            raise ValueError("one new identifier per item is required")
        copied = tuple(
            PlanItem.of(new_id, item)
            for item, new_id in zip(self.items, item_ids, strict=True)
        )
        return TreatmentPlan.draft(
            plan_id=new_plan_id,
            clinic_id=self.clinic_id,
            patient_id=self.patient_id,
            version=version,
            target_profile_id=self.target_profile_id,
            created_by=created_by,
            at=at,
            items=copied,
            template_id=self.template_id,
            previous_plan_id=self.plan_id,
            titration_rules=self.titration_rules,
            notes=self.notes,
        )

    def open_new_version(
        self,
        *,
        new_plan_id: UUID,
        item_ids: tuple[UUID, ...],
        version: int,
        created_by: UUID,
        at: datetime,
    ) -> TreatmentPlan:
        """A new draft from an active plan: the only way to change a treatment."""
        self._require(PlanStatus.ACTIVE, "version")
        return self.copy_for_new_version(
            new_plan_id=new_plan_id,
            item_ids=item_ids,
            version=version,
            created_by=created_by,
            at=at,
        )

    def create_memento(self, taken_at: datetime) -> TreatmentPlanMemento:
        """P16: a photo of this plan, with primitive data only."""
        data: dict[str, Any] = {
            "plan_id": str(self.plan_id),
            "clinic_id": str(self.clinic_id),
            "patient_id": str(self.patient_id),
            "version": self.version,
            "status": self.status.value,
            "target_profile_id": str(self.target_profile_id),
            "template_id": _text_or_none(self.template_id),
            "previous_plan_id": _text_or_none(self.previous_plan_id),
            "created_by": str(self.created_by),
            "titration_rules": rules_to_primitive(self.titration_rules),
            "notes": self.notes,
            "items": [plan_item_to_primitive(item) for item in self.items],
        }
        return TreatmentPlanMemento(
            schema_version=MEMENTO_SCHEMA_VERSION, taken_at=taken_at, data=data
        )

    @classmethod
    def from_memento(cls, memento: TreatmentPlanMemento) -> TreatmentPlan:
        """P16: the plan a photo describes, as it was when the photo was taken."""
        data = memento.data
        at = memento.taken_at
        return cls(
            plan_id=UUID(str(data["plan_id"])),
            clinic_id=UUID(str(data["clinic_id"])),
            patient_id=UUID(str(data["patient_id"])),
            version=int(data["version"]),
            status=PlanStatus(data["status"]),
            target_profile_id=UUID(str(data["target_profile_id"])),
            created_by=UUID(str(data["created_by"])),
            created_at=at,
            updated_at=at,
            items=tuple(plan_item_from_primitive(item) for item in data["items"]),
            template_id=_uuid_or_none(data["template_id"]),
            previous_plan_id=_uuid_or_none(data["previous_plan_id"]),
            titration_rules=rules_from_primitive(data["titration_rules"]),
            notes=data["notes"],
        )

    def _require(self, status: PlanStatus, action: str) -> None:
        if self.status is not status:
            raise InvalidStateTransitionError(MACHINE_NAME, self.status.value, action)


def _text_or_none(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _uuid_or_none(value: Any) -> UUID | None:
    return None if value is None else UUID(str(value))
