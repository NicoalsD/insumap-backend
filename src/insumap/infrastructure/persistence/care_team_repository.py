"""``clinic.care_team_assignments``, the patient directory and the staff lookup."""

from __future__ import annotations

from collections.abc import Sequence
from typing import final, override
from uuid import UUID

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError

from insumap.application.access.ports import (
    CareTeamAssignmentPort,
    PatientDirectoryPort,
)
from insumap.application.care_team.ports import (
    AssignmentFilter,
    CareTeamRepositoryPort,
    StaffLookupPort,
)
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.access.policy import PatientRef
from insumap.domain.care_team.assignment import (
    DOCTOR_ALREADY_ASSIGNED,
    CareAssignment,
    CareTeam,
    CareTeamChange,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.identity.roles import Role
from insumap.infrastructure.persistence.orm import (
    CareAssignmentOrm,
    MembershipOrm,
    PatientOrm,
    RoleOrm,
    UserOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

OPEN_PAIR_INDEX = "ux_care_team_open_pair"
ACTIVE_STATUS = "ACTIVE"


def _assignment(row: CareAssignmentOrm) -> CareAssignment:
    return CareAssignment(
        assignment_id=row.id,
        clinic_id=row.clinic_id,
        patient_id=row.patient_id,
        doctor_user_id=row.doctor_user_id,
        is_primary=row.is_primary,
        assigned_by=row.assigned_by,
        assigned_at=row.assigned_at,
        ended_at=row.ended_at,
        ended_by=row.ended_by,
        end_reason=row.end_reason,
    )


@final
class CareTeamRepository(CareTeamRepositoryPort, CareTeamAssignmentPort):
    """What the session may see: a doctor sees his rows, an administrator the clinic."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get_assignment(self, assignment_id: UUID) -> CareAssignment | None:
        row = self._current.get().get(CareAssignmentOrm, assignment_id)
        return None if row is None else _assignment(row)

    @override
    def open_team(self, patient_id: UUID) -> CareTeam:
        rows = self._current.get().scalars(
            select(CareAssignmentOrm)
            .where(
                CareAssignmentOrm.patient_id == patient_id,
                CareAssignmentOrm.ended_at.is_(None),
            )
            .order_by(CareAssignmentOrm.id)
        )
        return CareTeam(
            patient_id=patient_id,
            open_assignments=tuple(_assignment(row) for row in rows),
        )

    @override
    def for_patient(self, patient_id: UUID) -> Sequence[CareAssignment]:
        rows = self._current.get().scalars(
            select(CareAssignmentOrm).where(CareAssignmentOrm.patient_id == patient_id)
        )
        return [_assignment(row) for row in rows]

    @override
    def apply(self, change: CareTeamChange) -> None:
        session = self._current.get()
        try:
            for assignment in change.updated:
                session.execute(
                    update(CareAssignmentOrm)
                    .where(CareAssignmentOrm.id == assignment.assignment_id)
                    .values(
                        is_primary=assignment.is_primary,
                        ended_at=assignment.ended_at,
                        ended_by=assignment.ended_by,
                        end_reason=assignment.end_reason,
                    )
                )
            for assignment in change.added:
                session.add(
                    CareAssignmentOrm(
                        id=assignment.assignment_id,
                        clinic_id=assignment.clinic_id,
                        patient_id=assignment.patient_id,
                        doctor_user_id=assignment.doctor_user_id,
                        is_primary=assignment.is_primary,
                        assigned_by=assignment.assigned_by,
                        assigned_at=assignment.assigned_at,
                    )
                )
            session.flush()
        except IntegrityError as error:
            if OPEN_PAIR_INDEX in str(error.orig):
                raise ConflictError(DOCTOR_ALREADY_ASSIGNED) from None
            raise

    @override
    def list_assignments(
        self, filters: AssignmentFilter, page: PageRequest
    ) -> Page[CareAssignment]:
        statement = select(CareAssignmentOrm).order_by(CareAssignmentOrm.id)
        if page.after is not None:
            statement = statement.where(CareAssignmentOrm.id > page.after)
        if filters.patient_id is not None:
            statement = statement.where(
                CareAssignmentOrm.patient_id == filters.patient_id
            )
        if filters.doctor_id is not None:
            statement = statement.where(
                CareAssignmentOrm.doctor_user_id == filters.doctor_id
            )
        if filters.ended is not None:
            statement = statement.where(
                CareAssignmentOrm.ended_at.is_not(None)
                if filters.ended
                else CareAssignmentOrm.ended_at.is_(None)
            )
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_assignment(row) for row in rows],
            limit=page.limit,
            key=lambda assignment: assignment.assignment_id,
        )

    @override
    def count_open_for_doctor(self, doctor_user_id: UUID) -> int:
        count = self._current.get().scalar(
            select(func.count())
            .select_from(CareAssignmentOrm)
            .where(
                CareAssignmentOrm.doctor_user_id == doctor_user_id,
                CareAssignmentOrm.ended_at.is_(None),
            )
        )
        return int(count or 0)


@final
class PatientDirectoryRepository(PatientDirectoryPort):
    """Patients under row level security: another clinic's rows do not exist."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find(self, patient_id: UUID) -> PatientRef | None:
        row = (
            self._current.get()
            .execute(
                select(PatientOrm.id, PatientOrm.clinic_id, PatientOrm.user_id).where(
                    PatientOrm.id == patient_id
                )
            )
            .first()
        )
        if row is None:
            return None
        return PatientRef(
            patient_id=row.id, clinic_id=row.clinic_id, user_id=row.user_id
        )


@final
class StaffLookupRepository(StaffLookupPort):
    """Active doctors of the session clinic, through the membership and the role."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def is_active_doctor(self, user_id: UUID) -> bool:
        statement = select(
            exists().where(
                UserOrm.id == user_id,
                UserOrm.status == ACTIVE_STATUS,
                MembershipOrm.user_id == UserOrm.id,
                MembershipOrm.is_active.is_(True),
                RoleOrm.id == MembershipOrm.role_id,
                RoleOrm.code == Role.DOCTOR.value,
            )
        )
        return bool(self._current.get().scalar(statement))
