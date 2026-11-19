"""``care.target_profiles`` (catalog) and ``care.patient_target_assignments``."""

from __future__ import annotations

from typing import Any, cast, final, override
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.targets.commands import CODE_TAKEN, VERSION_RACE
from insumap.application.targets.ports import (
    PatientTargetAssignmentPort,
    TargetProfileCatalogPort,
)
from insumap.domain.common.errors import ConflictError
from insumap.domain.metrics.target_profile_version import (
    ACTIVE,
    RETIRED,
    PatientTargetAssignment,
    TargetProfileValues,
    TargetProfileVersion,
)
from insumap.infrastructure.persistence.metrics_orm import (
    PatientTargetAssignmentOrm,
    TargetProfileOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession

CODE_INDEX = "ux_target_profiles_version"
ACTIVE_INDEX = "ux_target_profiles_active"
OPEN_ASSIGNMENT_INDEX = "ux_patient_target_open"
ASSIGNMENT_CONFLICT = "patient_target_conflict"


def _version(row: TargetProfileOrm) -> TargetProfileVersion:
    values = TargetProfileValues(
        label=row.label,
        population=row.population,
        is_default=row.is_default,
        range_low_mg_dl=row.range_low_mg_dl,
        range_high_mg_dl=row.range_high_mg_dl,
        very_low_mg_dl=row.very_low_mg_dl,
        very_high_mg_dl=row.very_high_mg_dl,
        tir_min_pct=row.tir_min_pct,
        tbr_l1_max_pct=row.tbr_l1_max_pct,
        tbr_l2_max_pct=row.tbr_l2_max_pct,
        tar_l1_max_pct=row.tar_l1_max_pct,
        tar_l2_max_pct=row.tar_l2_max_pct,
        cv_max_pct=row.cv_max_pct,
        min_data_sufficiency_pct=row.min_data_sufficiency_pct,
        min_days=row.min_days,
        max_gap_minutes=row.max_gap_minutes,
        hypo_episode_min_minutes=row.hypo_episode_min_minutes,
        min_readings_for_cv=row.min_readings_for_cv,
        min_readings_for_cv_smbg=row.min_readings_for_cv_smbg,
        night_start=row.night_start,
        night_end=row.night_end,
        source_reference=row.source_reference,
        hba1c_goal_pct=row.hba1c_goal_pct,
        fasting_low_mg_dl=row.fasting_low_mg_dl,
        fasting_high_mg_dl=row.fasting_high_mg_dl,
        postprandial_max_mg_dl=row.postprandial_max_mg_dl,
        postprandial_1h_max_mg_dl=row.postprandial_1h_max_mg_dl,
        postprandial_2h_max_mg_dl=row.postprandial_2h_max_mg_dl,
    )
    return TargetProfileVersion(
        id=row.id,
        clinic_id=row.clinic_id,
        code=row.code,
        version=row.version,
        status=row.status,
        values=values,
        created_at=row.created_at,
        created_by=row.created_by,
        change_reason=row.change_reason,
        activated_at=row.activated_at,
    )


def _row(version: TargetProfileVersion) -> TargetProfileOrm:
    v = version.values
    return TargetProfileOrm(
        id=version.id,
        clinic_id=version.clinic_id,
        code=version.code,
        label=v.label,
        population=v.population,
        version=version.version,
        status=version.status,
        is_default=v.is_default,
        range_low_mg_dl=v.range_low_mg_dl,
        range_high_mg_dl=v.range_high_mg_dl,
        very_low_mg_dl=v.very_low_mg_dl,
        very_high_mg_dl=v.very_high_mg_dl,
        tir_min_pct=v.tir_min_pct,
        tbr_l1_max_pct=v.tbr_l1_max_pct,
        tbr_l2_max_pct=v.tbr_l2_max_pct,
        tar_l1_max_pct=v.tar_l1_max_pct,
        tar_l2_max_pct=v.tar_l2_max_pct,
        cv_max_pct=v.cv_max_pct,
        min_data_sufficiency_pct=v.min_data_sufficiency_pct,
        min_days=v.min_days,
        max_gap_minutes=v.max_gap_minutes,
        hypo_episode_min_minutes=v.hypo_episode_min_minutes,
        min_readings_for_cv=v.min_readings_for_cv,
        min_readings_for_cv_smbg=v.min_readings_for_cv_smbg,
        night_start=v.night_start,
        night_end=v.night_end,
        source_reference=v.source_reference,
        hba1c_goal_pct=v.hba1c_goal_pct,
        fasting_low_mg_dl=v.fasting_low_mg_dl,
        fasting_high_mg_dl=v.fasting_high_mg_dl,
        postprandial_max_mg_dl=v.postprandial_max_mg_dl,
        postprandial_1h_max_mg_dl=v.postprandial_1h_max_mg_dl,
        postprandial_2h_max_mg_dl=v.postprandial_2h_max_mg_dl,
        change_reason=version.change_reason,
        created_by=version.created_by,
        activated_at=version.activated_at,
        created_at=version.created_at,
    )


@final
class TargetProfileCatalogRepository(TargetProfileCatalogPort):
    """Profiles under row level security: the clinic's rows and the global seeds."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def list_active(
        self, population: str | None, page: PageRequest
    ) -> Page[TargetProfileVersion]:
        statement = (
            select(TargetProfileOrm)
            .where(TargetProfileOrm.status == ACTIVE)
            .order_by(TargetProfileOrm.id)
        )
        if population is not None:
            statement = statement.where(TargetProfileOrm.population == population)
        if page.after is not None:
            statement = statement.where(TargetProfileOrm.id > page.after)
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_version(row) for row in rows],
            limit=page.limit,
            key=lambda version: version.id,
        )

    @override
    def get(self, profile_id: UUID) -> TargetProfileVersion | None:
        row = self._current.get().get(TargetProfileOrm, profile_id)
        return None if row is None else _version(row)

    @override
    def versions_of(
        self, clinic_id: UUID | None, code: str
    ) -> tuple[TargetProfileVersion, ...]:
        rows = self._current.get().scalars(
            select(TargetProfileOrm)
            .where(
                TargetProfileOrm.code == code,
                TargetProfileOrm.clinic_id.is_not_distinct_from(clinic_id),
            )
            .order_by(TargetProfileOrm.version)
        )
        return tuple(_version(row) for row in rows)

    @override
    def active_of_clinic(
        self, clinic_id: UUID, code: str
    ) -> TargetProfileVersion | None:
        row = self._current.get().scalar(
            select(TargetProfileOrm).where(
                TargetProfileOrm.clinic_id == clinic_id,
                TargetProfileOrm.code == code,
                TargetProfileOrm.status == ACTIVE,
            )
        )
        return None if row is None else _version(row)

    @override
    def code_exists(self, clinic_id: UUID, code: str) -> bool:
        found = self._current.get().scalar(
            select(
                exists().where(
                    TargetProfileOrm.clinic_id == clinic_id,
                    TargetProfileOrm.code == code,
                )
            )
        )
        return bool(found)

    @override
    def retire(self, profile_id: UUID) -> bool:
        # Only the status changes: the trigger admits nothing else on an ACTIVE row.
        result = self._current.get().execute(
            update(TargetProfileOrm)
            .where(TargetProfileOrm.id == profile_id, TargetProfileOrm.status == ACTIVE)
            .values(status=RETIRED)
            .execution_options(synchronize_session=False)
        )
        return cast(CursorResult[Any], result).rowcount == 1

    @override
    def insert(self, version: TargetProfileVersion) -> None:
        session = self._current.get()
        session.add(_row(version))
        try:
            session.flush()
        except IntegrityError as error:
            if CODE_INDEX in str(error.orig) or ACTIVE_INDEX in str(error.orig):
                raise ConflictError(
                    VERSION_RACE if version.version > 1 else CODE_TAKEN
                ) from None
            raise


@final
class PatientTargetAssignmentRepository(PatientTargetAssignmentPort):
    """One open assignment per patient; the end is written before the new insert."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def open_for_patient(self, patient_id: UUID) -> PatientTargetAssignment | None:
        row = self._current.get().scalar(
            select(PatientTargetAssignmentOrm).where(
                PatientTargetAssignmentOrm.patient_id == patient_id,
                PatientTargetAssignmentOrm.ended_at.is_(None),
            )
        )
        if row is None:
            return None
        return PatientTargetAssignment(
            id=row.id,
            clinic_id=row.clinic_id,
            patient_id=row.patient_id,
            target_profile_id=row.target_profile_id,
            assigned_by=row.assigned_by,
            assigned_at=row.assigned_at,
            ended_at=row.ended_at,
        )

    @override
    def end(self, assignment: PatientTargetAssignment) -> None:
        self._current.get().execute(
            update(PatientTargetAssignmentOrm)
            .where(PatientTargetAssignmentOrm.id == assignment.id)
            .values(ended_at=assignment.ended_at)
            .execution_options(synchronize_session=False)
        )

    @override
    def insert(self, assignment: PatientTargetAssignment) -> None:
        session = self._current.get()
        session.add(
            PatientTargetAssignmentOrm(
                id=assignment.id,
                clinic_id=assignment.clinic_id,
                patient_id=assignment.patient_id,
                target_profile_id=assignment.target_profile_id,
                assigned_by=assignment.assigned_by,
                assigned_at=assignment.assigned_at,
                ended_at=assignment.ended_at,
            )
        )
        try:
            session.flush()
        except IntegrityError as error:
            if OPEN_ASSIGNMENT_INDEX in str(error.orig):
                raise ConflictError(ASSIGNMENT_CONFLICT) from None
            raise
