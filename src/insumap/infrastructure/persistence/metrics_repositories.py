"""PostgreSQL readers of the metrics inputs: target profile and glucose series."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Final, final, override
from uuid import UUID

from sqlalchemy import select

from insumap.application.metrics.ports import GlucoseSeriesPort, TargetProfilePort
from insumap.domain.metrics.target_profile import PatientTargets, TargetProfile
from insumap.domain.metrics.window import GlucosePoint
from insumap.domain.monitoring.glucose import ReadingContext, ReadingSource
from insumap.infrastructure.persistence.metrics_orm import (
    PatientTargetAssignmentOrm,
    TargetProfileOrm,
)
from insumap.infrastructure.persistence.monitoring_orm import GlucoseReadingOrm
from insumap.infrastructure.persistence.monitoring_repositories import is_current
from insumap.infrastructure.persistence.orm import ClinicOrm, PatientOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

ACTIVE: Final = "ACTIVE"
ADULT_POPULATION: Final = "ADULT"
POPULATION_BY_DIABETES_TYPE: Final = {"GDM": "PREGNANCY_T2D_GDM"}
"""Population of the default target profile by ``clinic.patients.diabetes_type``.

The documents say the diabetes type "selects the population" but do not list the
mapping; every type not listed here uses ``ADULT_POPULATION`` (API.md, G-gap).
"""


def _profile(row: TargetProfileOrm) -> TargetProfile:
    return TargetProfile(
        id=row.id,
        code=row.code,
        version=row.version,
        population=row.population,
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
    )


@final
class TargetProfileRepository(TargetProfilePort):
    """The profile assigned to the patient, or the default of its population."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def for_patient(self, patient_id: UUID) -> PatientTargets | None:
        session = self._current.get()
        patient = session.execute(
            select(PatientOrm.clinic_id, PatientOrm.diabetes_type).where(
                PatientOrm.id == patient_id
            )
        ).first()
        if patient is None:
            return None
        clinic_id, diabetes_type = patient
        profile = session.execute(
            select(TargetProfileOrm)
            .join(
                PatientTargetAssignmentOrm,
                PatientTargetAssignmentOrm.target_profile_id == TargetProfileOrm.id,
            )
            .where(
                PatientTargetAssignmentOrm.patient_id == patient_id,
                PatientTargetAssignmentOrm.ended_at.is_(None),
            )
        ).scalar_one_or_none()
        if profile is None:
            population = POPULATION_BY_DIABETES_TYPE.get(
                diabetes_type, ADULT_POPULATION
            )
            profile = session.execute(
                select(TargetProfileOrm)
                .where(
                    TargetProfileOrm.population == population,
                    TargetProfileOrm.is_default.is_(True),
                    TargetProfileOrm.status == ACTIVE,
                    (TargetProfileOrm.clinic_id == clinic_id)
                    | TargetProfileOrm.clinic_id.is_(None),
                )
                .order_by(TargetProfileOrm.clinic_id.is_(None))
                .limit(1)
            ).scalar_one_or_none()
        if profile is None:
            return None
        timezone = session.execute(
            select(ClinicOrm.timezone).where(ClinicOrm.id == clinic_id)
        ).scalar_one()
        return PatientTargets(
            patient_id=patient_id, profile=_profile(profile), timezone=timezone
        )


@final
class GlucoseSeriesRepository(GlucoseSeriesPort):
    """The current readings of a patient: not annulled and not superseded."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def points(
        self, patient_id: UUID, start: datetime, end: datetime
    ) -> Sequence[GlucosePoint]:
        orm = GlucoseReadingOrm
        rows = self._current.get().execute(
            select(orm.measured_at, orm.value_mg_dl, orm.source, orm.context)
            .where(
                orm.patient_id == patient_id,
                orm.measured_at >= start,
                orm.measured_at < end,
                is_current(orm),
            )
            .order_by(orm.measured_at)
        )
        return [
            GlucosePoint(
                at=at,
                mg_dl=value,
                source=ReadingSource(source),
                context=None if context is None else ReadingContext(context),
            )
            for at, value, source, context in rows
        ]
