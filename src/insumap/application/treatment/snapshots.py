"""The caretaker of the plan photos (P16): it saves a photo before each change."""

from __future__ import annotations

from datetime import datetime
from typing import final
from uuid import UUID

from insumap.application.treatment.ports import TreatmentPlanSnapshotPort
from insumap.domain.treatment.plan import TreatmentPlan


@final
class PlanSnapshotCaretaker:
    """Takes the photo of a plan before a change and never reads it back.

    The use cases ask it, inside their transaction, to keep the state a change is
    about to replace. Restoring a photo is a separate use case.

    Pattern: P16 Memento (caretaker)
    """

    def __init__(self, snapshots: TreatmentPlanSnapshotPort) -> None:
        self._snapshots = snapshots

    def before_change(
        self, plan: TreatmentPlan, *, taken_by: UUID, at: datetime
    ) -> None:
        """Keep the photo of ``plan`` as it is now, taken at ``at``."""
        self._snapshots.append(
            plan_id=plan.plan_id,
            number=self._snapshots.next_number(plan.plan_id),
            memento=plan.create_memento(taken_at=at),
            taken_by=taken_by,
        )
