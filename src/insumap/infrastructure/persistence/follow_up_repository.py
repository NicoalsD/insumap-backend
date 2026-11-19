"""``care.follow_ups`` for the controls (kind ``CONTROL``), under row level security."""

from __future__ import annotations

from typing import Final, final, override
from uuid import UUID

from sqlalchemy import select

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.follow_ups.ports import FollowUpRepositoryPort
from insumap.domain.follow_ups.follow_up import FollowUp, FollowUpStatus
from insumap.infrastructure.persistence.messaging_orm import FollowUpOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

CONTROL_KIND: Final = "CONTROL"
MANUAL_SOURCE: Final = "MANUAL"


def _follow_up(row: FollowUpOrm) -> FollowUp:
    if row.scheduled_for is None or row.assigned_to is None:
        # A control always has a date and an attendant (CHECK of the schema).
        raise RuntimeError("control without date or attendant")
    return FollowUp(
        follow_up_id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        status=FollowUpStatus(row.status),
        scheduled_for=row.scheduled_for,
        assigned_to=row.assigned_to,
        created_by=row.created_by,
        title=row.title,
        created_at=row.created_at,
        result_note=row.result_note,
        closed_at=row.closed_at,
    )


@final
class FollowUpRepository(FollowUpRepositoryPort):
    """Controls only: outreach tasks of the clinic are not read by this API."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def insert(self, follow_up: FollowUp) -> None:
        session = self._current.get()
        session.add(
            FollowUpOrm(
                id=follow_up.follow_up_id,
                clinic_id=follow_up.clinic_id,
                patient_id=follow_up.patient_id,
                kind=CONTROL_KIND,
                status=follow_up.status.value,
                scheduled_for=follow_up.scheduled_for,
                assigned_to=follow_up.assigned_to,
                source=MANUAL_SOURCE,
                title=follow_up.title,
                created_by=follow_up.created_by,
                created_at=follow_up.created_at,
                updated_at=follow_up.created_at,
            )
        )
        session.flush()

    @override
    def get(self, follow_up_id: UUID) -> FollowUp | None:
        row = (
            self._current.get()
            .scalars(
                select(FollowUpOrm).where(
                    FollowUpOrm.id == follow_up_id, FollowUpOrm.kind == CONTROL_KIND
                )
            )
            .first()
        )
        return None if row is None else _follow_up(row)

    @override
    def update(self, follow_up: FollowUp) -> None:
        session = self._current.get()
        row = session.get(FollowUpOrm, follow_up.follow_up_id)
        if row is None:
            raise RuntimeError("follow-up vanished inside its transaction")
        row.status = follow_up.status.value
        row.result_note = follow_up.result_note
        row.closed_at = follow_up.closed_at
        # Only closing writes a control, so its close time is the last change.
        row.updated_at = follow_up.closed_at or follow_up.created_at
        session.flush()

    @override
    def list_for_patient(
        self,
        patient_id: UUID,
        *,
        status: FollowUpStatus | None,
        page: PageRequest,
    ) -> Page[FollowUp]:
        statement = select(FollowUpOrm).where(
            FollowUpOrm.patient_id == patient_id,
            FollowUpOrm.kind == CONTROL_KIND,
        )
        if status is not None:
            statement = statement.where(FollowUpOrm.status == status.value)
        if page.after is not None:
            statement = statement.where(FollowUpOrm.id < page.after)
        rows = self._current.get().scalars(
            statement.order_by(FollowUpOrm.id.desc()).limit(page.limit + 1)
        )
        return build_page(
            [_follow_up(row) for row in rows],
            limit=page.limit,
            key=lambda follow_up: follow_up.follow_up_id,
        )
