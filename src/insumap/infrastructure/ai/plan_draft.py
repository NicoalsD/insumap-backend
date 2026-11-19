"""The draft of a patient's next plan version, opened on approval (P05)."""

from __future__ import annotations

from datetime import datetime
from typing import final, override
from uuid import UUID

from insumap.application.ai.recommendations import OpenPlanDraftPort
from insumap.application.common.ids import IdGenerator
from insumap.application.treatment.ports import TreatmentPlanRepositoryPort


@final
class TreatmentPlanDraftOpener(OpenPlanDraftPort):
    """Writes a ``DRAFT`` copy of the active plan; the active plan does not change.

    The doctor activates the draft later, so an approval never changes the
    treatment of the patient by itself (Modulo-IA 3.2).
    """

    def __init__(self, plans: TreatmentPlanRepositoryPort, ids: IdGenerator) -> None:
        self._plans = plans
        self._ids = ids

    @override
    def open_draft(self, patient_id: UUID, *, by: UUID, at: datetime) -> UUID | None:
        active = self._plans.active_for(patient_id)
        if active is None:
            return None
        draft = active.open_new_version(
            new_plan_id=self._ids.new_id(),
            item_ids=tuple(self._ids.new_id() for _ in active.items),
            version=self._plans.highest_version(patient_id) + 1,
            created_by=by,
            at=at,
        )
        self._plans.insert(draft)
        return draft.plan_id
