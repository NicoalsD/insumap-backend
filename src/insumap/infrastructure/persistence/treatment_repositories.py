"""PostgreSQL repositories of the treatment plans and protocol templates.

Every statement runs on the session of the open transaction, so row level
security (the clinic of the session and the role) applies to each query. The
mapping between ``*Orm`` rows and domain values lives here and nowhere else.
"""

from __future__ import annotations

from typing import Any, Final, final, override
from uuid import UUID

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.metrics.ports import TargetProfilePort
from insumap.application.treatment.ports import (
    ProtocolTemplateRepositoryPort,
    StoredSnapshot,
    TargetProfileLookupPort,
    TreatmentPlanRepositoryPort,
    TreatmentPlanSnapshotPort,
)
from insumap.domain.treatment.content import (
    InsulinKind,
    ItemSpec,
    ItemType,
    PlanItem,
)
from insumap.domain.treatment.plan import (
    PlanStatus,
    TreatmentPlan,
    TreatmentPlanMemento,
)
from insumap.domain.treatment.primitives import (
    item_to_primitive,
    rules_from_primitive,
    rules_to_primitive,
    template_content_from_primitive,
    template_content_to_primitive,
)
from insumap.domain.treatment.template import ProtocolTemplate, TemplateStatus
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.persistence.treatment_orm import (
    ProtocolTemplateOrm,
    TreatmentPlanItemOrm,
    TreatmentPlanOrm,
    TreatmentPlanSnapshotOrm,
)

MEMENTO_SCHEMA_VERSION: Final = 1
CLINIC_KEY: Final = "clinic_id"


def _clinic_filter(column: Any, clinic_id: UUID | None) -> ColumnElement[bool]:
    """``IS NULL`` for a global seed, equality for a clinic (NULLS NOT DISTINCT)."""
    condition: ColumnElement[bool] = (
        column.is_(None) if clinic_id is None else column == clinic_id
    )
    return condition


def _template_of(row: ProtocolTemplateOrm) -> ProtocolTemplate:
    return ProtocolTemplate(
        template_id=row.id,
        clinic_id=row.clinic_id,
        code=row.code,
        name=row.name,
        version=row.version,
        status=TemplateStatus(row.status),
        content=template_content_from_primitive(row.content),
        created_by=row.created_by,
        created_at=row.created_at,
        default_target_profile_id=row.default_target_profile_id,
    )


def _template_row(template: ProtocolTemplate) -> ProtocolTemplateOrm:
    return ProtocolTemplateOrm(
        id=template.template_id,
        clinic_id=template.clinic_id,
        code=template.code,
        name=template.name,
        version=template.version,
        status=template.status.value,
        default_target_profile_id=template.default_target_profile_id,
        content=template_content_to_primitive(template.content),
        created_by=template.created_by,
        created_at=template.created_at,
    )


def _item_of(row: TreatmentPlanItemOrm) -> PlanItem:
    spec = ItemSpec(
        item_type=ItemType(row.item_type),
        name=row.name,
        insulin_kind=None
        if row.insulin_kind is None
        else InsulinKind(row.insulin_kind),
        dose_units=row.dose_units,
        time_of_day=row.time_of_day,
        days_of_week=None if row.days_of_week is None else tuple(row.days_of_week),
        instructions=row.instructions,
        sort_order=row.sort_order,
    )
    return PlanItem.of(row.id, spec)


def _item_row(plan: TreatmentPlan, index: int, item: PlanItem) -> TreatmentPlanItemOrm:
    primitive = item_to_primitive(item)
    return TreatmentPlanItemOrm(
        id=item.item_id,
        clinic_id=plan.clinic_id,
        plan_id=plan.plan_id,
        item_type=primitive["item_type"],
        insulin_kind=primitive["insulin_kind"],
        name=primitive["name"],
        dose_units=item.dose_units,
        time_of_day=item.time_of_day,
        days_of_week=primitive["days_of_week"],
        instructions=primitive["instructions"],
        sort_order=index,
    )


def _plan_fields(plan: TreatmentPlan) -> dict[str, object]:
    return {
        "clinic_id": plan.clinic_id,
        "patient_id": plan.patient_id,
        "version": plan.version,
        "status": plan.status.value,
        "template_id": plan.template_id,
        "previous_plan_id": plan.previous_plan_id,
        "target_profile_id": plan.target_profile_id,
        "titration_rules": rules_to_primitive(plan.titration_rules),
        "notes": plan.notes,
        "created_by": plan.created_by,
        "activated_by": plan.activated_by,
        "activated_at": plan.activated_at,
        "superseded_at": plan.superseded_at,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "lock_version": plan.lock_version,
    }


@final
class ProtocolTemplateRepository(ProtocolTemplateRepositoryPort):
    """``care.protocol_templates``: a clinic's versions and the global seeds."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    def _session(self) -> Session:
        return self._current.get()

    @override
    def get(self, template_id: UUID) -> ProtocolTemplate | None:
        row = self._session().get(ProtocolTemplateOrm, template_id)
        return None if row is None else _template_of(row)

    @override
    def family(self, clinic_id: UUID | None, code: str) -> tuple[ProtocolTemplate, ...]:
        orm = ProtocolTemplateOrm
        rows = (
            self._session()
            .execute(
                select(orm)
                .where(orm.code == code, _clinic_filter(orm.clinic_id, clinic_id))
                .order_by(orm.version)
            )
            .scalars()
            .all()
        )
        return tuple(_template_of(row) for row in rows)

    @override
    def insert(self, template: ProtocolTemplate) -> None:
        self._session().add(_template_row(template))
        self._session().flush()

    @override
    def retire(self, template: ProtocolTemplate) -> None:
        row = self._session().get(ProtocolTemplateOrm, template.template_id)
        if row is None:
            return
        row.status = template.status.value
        self._session().flush()

    @override
    def list_latest(
        self, status: TemplateStatus | None, page: PageRequest
    ) -> Page[ProtocolTemplate]:
        orm = ProtocolTemplateOrm
        rows = self._session().execute(select(orm)).scalars().all()
        latest: dict[tuple[UUID | None, str], ProtocolTemplateOrm] = {}
        for row in rows:
            key = (row.clinic_id, row.code)
            if key not in latest or row.version > latest[key].version:
                latest[key] = row
        visible = sorted(
            (
                _template_of(row)
                for row in latest.values()
                if status is None or row.status == status.value
            ),
            key=lambda template: template.template_id,
        )
        after = [t for t in visible if page.after is None or t.template_id > page.after]
        return build_page(
            after[: page.limit + 1], limit=page.limit, key=lambda t: t.template_id
        )


@final
class TreatmentPlanRepository(TreatmentPlanRepositoryPort):
    """``care.treatment_plans`` with its items, ordered as the plan lists them."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    def _session(self) -> Session:
        return self._current.get()

    def _with_items(self, row: TreatmentPlanOrm) -> TreatmentPlan:
        items = (
            self._session()
            .execute(
                select(TreatmentPlanItemOrm)
                .where(TreatmentPlanItemOrm.plan_id == row.id)
                .order_by(TreatmentPlanItemOrm.sort_order)
            )
            .scalars()
            .all()
        )
        return TreatmentPlan(
            plan_id=row.id,
            clinic_id=row.clinic_id,
            patient_id=row.patient_id,
            version=row.version,
            status=PlanStatus(row.status),
            target_profile_id=row.target_profile_id,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
            items=tuple(_item_of(item) for item in items),
            template_id=row.template_id,
            previous_plan_id=row.previous_plan_id,
            titration_rules=rules_from_primitive(row.titration_rules),
            notes=row.notes,
            activated_by=row.activated_by,
            activated_at=row.activated_at,
            superseded_at=row.superseded_at,
            lock_version=row.lock_version,
        )

    @override
    def get(self, plan_id: UUID) -> TreatmentPlan | None:
        row = self._session().get(TreatmentPlanOrm, plan_id)
        return None if row is None else self._with_items(row)

    @override
    def active_for(self, patient_id: UUID) -> TreatmentPlan | None:
        orm = TreatmentPlanOrm
        row = (
            self._session()
            .execute(
                select(orm).where(
                    orm.patient_id == patient_id, orm.status == PlanStatus.ACTIVE.value
                )
            )
            .scalar_one_or_none()
        )
        return None if row is None else self._with_items(row)

    @override
    def highest_version(self, patient_id: UUID) -> int:
        orm = TreatmentPlanOrm
        found = (
            self._session()
            .execute(select(orm.version).where(orm.patient_id == patient_id))
            .scalars()
            .all()
        )
        return max(found, default=0)

    @override
    def insert(self, plan: TreatmentPlan) -> None:
        session = self._session()
        session.add(TreatmentPlanOrm(id=plan.plan_id, **_plan_fields(plan)))
        session.flush()
        self._write_items(plan)

    @override
    def update(self, plan: TreatmentPlan) -> None:
        row = self._session().get(TreatmentPlanOrm, plan.plan_id)
        if row is None:
            return
        for name, value in _plan_fields(plan).items():
            setattr(row, name, value)
        self._session().flush()

    @override
    def replace_items(self, plan: TreatmentPlan) -> None:
        self._session().execute(
            delete(TreatmentPlanItemOrm).where(
                TreatmentPlanItemOrm.plan_id == plan.plan_id
            )
        )
        self._write_items(plan)

    def _write_items(self, plan: TreatmentPlan) -> None:
        session = self._session()
        for index, item in enumerate(plan.items):
            session.add(_item_row(plan, index, item))
        session.flush()

    @override
    def list_for_patient(
        self, patient_id: UUID, status: PlanStatus | None, page: PageRequest
    ) -> Page[TreatmentPlan]:
        orm = TreatmentPlanOrm
        statement = select(orm).where(orm.patient_id == patient_id)
        if status is not None:
            statement = statement.where(orm.status == status.value)
        if page.after is not None:
            statement = statement.where(orm.id < page.after)
        rows = (
            self._session()
            .execute(statement.order_by(orm.id.desc()).limit(page.limit + 1))
            .scalars()
            .all()
        )
        plans = [self._with_items(row) for row in rows]
        return build_page(plans, limit=page.limit, key=lambda plan: plan.plan_id)


@final
class TreatmentPlanSnapshotRepository(TreatmentPlanSnapshotPort):
    """``care.treatment_plan_snapshots``: append-only photos (P16)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    def _session(self) -> Session:
        return self._current.get()

    @override
    def next_number(self, plan_id: UUID) -> int:
        orm = TreatmentPlanSnapshotOrm
        numbers = (
            self._session()
            .execute(select(orm.snapshot_no).where(orm.plan_id == plan_id))
            .scalars()
            .all()
        )
        return max(numbers, default=0) + 1

    @override
    def append(
        self,
        *,
        plan_id: UUID,
        number: int,
        memento: TreatmentPlanMemento,
        taken_by: UUID,
    ) -> None:
        clinic_id = UUID(str(memento.data[CLINIC_KEY]))
        self._session().add(
            TreatmentPlanSnapshotOrm(
                clinic_id=clinic_id,
                plan_id=plan_id,
                snapshot_no=number,
                snapshot=memento.data,
                taken_by=taken_by,
                taken_at=memento.taken_at,
            )
        )
        self._session().flush()

    @override
    def get(self, snapshot_id: UUID, plan_id: UUID) -> StoredSnapshot | None:
        orm = TreatmentPlanSnapshotOrm
        row = (
            self._session()
            .execute(select(orm).where(orm.id == snapshot_id, orm.plan_id == plan_id))
            .scalar_one_or_none()
        )
        return None if row is None else _snapshot_of(row)

    @override
    def list_for_plan(self, plan_id: UUID, page: PageRequest) -> Page[StoredSnapshot]:
        orm = TreatmentPlanSnapshotOrm
        statement = select(orm).where(orm.plan_id == plan_id)
        if page.after is not None:
            statement = statement.where(orm.id > page.after)
        rows = (
            self._session()
            .execute(statement.order_by(orm.id).limit(page.limit + 1))
            .scalars()
            .all()
        )
        return build_page(
            [_snapshot_of(row) for row in rows],
            limit=page.limit,
            key=lambda snapshot: snapshot.snapshot_id,
        )


def _snapshot_of(row: TreatmentPlanSnapshotOrm) -> StoredSnapshot:
    return StoredSnapshot(
        snapshot_id=row.id,
        plan_id=row.plan_id,
        number=row.snapshot_no,
        memento=TreatmentPlanMemento(
            schema_version=MEMENTO_SCHEMA_VERSION,
            taken_at=row.taken_at,
            data=dict(row.snapshot),
        ),
        taken_by=row.taken_by,
    )


@final
class TreatmentTargetLookup(TargetProfileLookupPort):
    """The goals profile of a new plan: the one the metrics of the patient use."""

    def __init__(self, targets: TargetProfilePort) -> None:
        self._targets = targets

    @override
    def profile_id_for(self, patient_id: UUID) -> UUID | None:
        found = self._targets.for_patient(patient_id)
        return None if found is None else found.profile.id
