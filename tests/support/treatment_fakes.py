"""In-memory doubles of the treatment ports, with the rules the database enforces.

The plan repository refuses what the triggers refuse: items change only in a
draft, and an active plan only moves to superseded. So a unit test notices an
ordering mistake (for example, activating before superseding) the way production
would. ``writes`` keeps the order of the writes for the tests that check it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import override
from uuid import UUID

from insumap.application.access.ports import (
    AccessPurpose,
    DataAccessAction,
    DataResource,
    PatientRecord,
    PatientRecordPort,
)
from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.treatment.ports import (
    ProtocolTemplateRepositoryPort,
    StoredSnapshot,
    TargetProfileLookupPort,
    TreatmentPlanRepositoryPort,
    TreatmentPlanSnapshotPort,
)
from insumap.domain.common.errors import ResourceNotFoundError
from insumap.domain.treatment.plan import (
    PlanStatus,
    TreatmentPlan,
    TreatmentPlanMemento,
)
from insumap.domain.treatment.template import ProtocolTemplate, TemplateStatus
from insumap.shared.errors import ErrorCode, InsumapError

CLINIC_ID = UUID(int=9)


class FakeTemplates(ProtocolTemplateRepositoryPort):
    def __init__(self, *rows: ProtocolTemplate) -> None:
        self.rows: dict[UUID, ProtocolTemplate] = {row.template_id: row for row in rows}
        self.writes: list[str] = []

    @override
    def get(self, template_id: UUID) -> ProtocolTemplate | None:
        return self.rows.get(template_id)

    @override
    def family(self, clinic_id: UUID | None, code: str) -> tuple[ProtocolTemplate, ...]:
        found = [
            row
            for row in self.rows.values()
            if row.clinic_id == clinic_id and row.code == code
        ]
        return tuple(sorted(found, key=lambda row: row.version))

    @override
    def insert(self, template: ProtocolTemplate) -> None:
        self.writes.append(f"insert:{template.version}")
        self.rows[template.template_id] = template

    @override
    def retire(self, template: ProtocolTemplate) -> None:
        self.writes.append(f"retire:{template.version}")
        self.rows[template.template_id] = template

    @override
    def list_latest(
        self, status: TemplateStatus | None, page: PageRequest
    ) -> Page[ProtocolTemplate]:
        latest: dict[tuple[UUID | None, str], ProtocolTemplate] = {}
        for row in self.rows.values():
            key = (row.clinic_id, row.code)
            if key not in latest or row.version > latest[key].version:
                latest[key] = row
        rows = [
            row
            for row in sorted(latest.values(), key=lambda r: r.template_id)
            if status is None or row.status is status
        ]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda r: r.template_id
        )


class FakePlans(TreatmentPlanRepositoryPort):
    def __init__(self, *rows: TreatmentPlan) -> None:
        self.rows: dict[UUID, TreatmentPlan] = {row.plan_id: row for row in rows}
        self.writes: list[str] = []

    @override
    def get(self, plan_id: UUID) -> TreatmentPlan | None:
        return self.rows.get(plan_id)

    @override
    def active_for(self, patient_id: UUID) -> TreatmentPlan | None:
        return next(
            (
                row
                for row in self.rows.values()
                if row.patient_id == patient_id and row.status is PlanStatus.ACTIVE
            ),
            None,
        )

    @override
    def highest_version(self, patient_id: UUID) -> int:
        versions = [
            row.version for row in self.rows.values() if row.patient_id == patient_id
        ]
        return max(versions, default=0)

    @override
    def insert(self, plan: TreatmentPlan) -> None:
        self.writes.append(f"insert:{plan.version}:{plan.status}")
        self.rows[plan.plan_id] = plan

    @override
    def update(self, plan: TreatmentPlan) -> None:
        current = self.rows[plan.plan_id]
        if (
            current.status is PlanStatus.ACTIVE
            and plan.status is not PlanStatus.SUPERSEDED
        ):
            raise InsumapError(ErrorCode.CONFLICT)
        self.writes.append(f"update:{plan.status}")
        self.rows[plan.plan_id] = replace(plan, items=current.items)

    @override
    def replace_items(self, plan: TreatmentPlan) -> None:
        if self.rows[plan.plan_id].status is not PlanStatus.DRAFT:
            raise InsumapError(ErrorCode.CONFLICT)
        self.writes.append("items")
        self.rows[plan.plan_id] = replace(self.rows[plan.plan_id], items=plan.items)

    @override
    def list_for_patient(
        self, patient_id: UUID, status: PlanStatus | None, page: PageRequest
    ) -> Page[TreatmentPlan]:
        rows = sorted(
            (
                row
                for row in self.rows.values()
                if row.patient_id == patient_id
                and (status is None or row.status is status)
            ),
            key=lambda row: row.plan_id,
        )
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda r: r.plan_id
        )


class FakeSnapshots(TreatmentPlanSnapshotPort):
    def __init__(self) -> None:
        self.rows: list[StoredSnapshot] = []
        self._ids = 0

    @override
    def next_number(self, plan_id: UUID) -> int:
        return 1 + sum(1 for row in self.rows if row.plan_id == plan_id)

    @override
    def append(
        self,
        *,
        plan_id: UUID,
        number: int,
        memento: TreatmentPlanMemento,
        taken_by: UUID,
    ) -> None:
        self._ids += 1
        self.rows.append(
            StoredSnapshot(
                snapshot_id=UUID(int=8000 + self._ids),
                plan_id=plan_id,
                number=number,
                memento=memento,
                taken_by=taken_by,
            )
        )

    @override
    def get(self, snapshot_id: UUID, plan_id: UUID) -> StoredSnapshot | None:
        return next(
            (
                row
                for row in self.rows
                if row.snapshot_id == snapshot_id and row.plan_id == plan_id
            ),
            None,
        )

    @override
    def list_for_plan(self, plan_id: UUID, page: PageRequest) -> Page[StoredSnapshot]:
        rows = [row for row in self.rows if row.plan_id == plan_id]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda r: r.snapshot_id
        )


class FakeTargets(TargetProfileLookupPort):
    def __init__(self, profile: UUID | None) -> None:
        self.profile = profile

    @override
    def profile_id_for(self, patient_id: UUID) -> UUID | None:
        return self.profile


class FakeAssignments(PatientRecordPort):
    """The access chain: only the listed doctor and patient pairs are assigned."""

    def __init__(self, *pairs: tuple[UUID, UUID]) -> None:
        self.assigned: set[tuple[UUID, UUID]] = set(pairs)
        self.reads: list[tuple[UUID, UUID, AccessPurpose, DataResource]] = []

    @override
    def read_record(
        self,
        actor: Actor,
        patient_id: UUID,
        purpose: AccessPurpose,
        resource: DataResource,
        action: DataAccessAction = DataAccessAction.READ,
    ) -> PatientRecord:
        if (actor.user_id, patient_id) not in self.assigned:
            raise ResourceNotFoundError
        self.reads.append((actor.user_id, patient_id, purpose, resource))
        return PatientRecord(patient_id=patient_id, clinic_id=CLINIC_ID)


def active(plan: TreatmentPlan) -> TreatmentPlan:
    """The same plan in the ``ACTIVE`` state, as a fixture."""
    return replace(plan, status=PlanStatus.ACTIVE)


class SequentialIds(IdGenerator):
    """Identifiers that never collide with the fixtures, which use small numbers."""

    def __init__(self, start: int = 50_000) -> None:
        self._last = start

    @override
    def new_id(self) -> UUID:
        self._last += 1
        return UUID(int=self._last)
