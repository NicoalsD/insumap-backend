"""PostgreSQL readers of the ``care`` parameters the records and metrics use.

The clinical parameters (validation thresholds, target profiles, the symptom
catalog) are rows the clinic administrator configures; nothing here has a
default. Reads run on the session of the open transaction, under RLS.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final, final, override
from uuid import UUID

from sqlalchemy import select

from insumap.application.monitoring.ports import (
    ActivePlanPort,
    SymptomCatalogPort,
    ValidationSettingsPort,
)
from insumap.domain.monitoring.records import SymptomEntry
from insumap.domain.monitoring.validation import ValidationParams
from insumap.infrastructure.persistence.monitoring_orm import (
    ReadingValidationSettingsOrm,
    SymptomCatalogOrm,
)
from insumap.infrastructure.persistence.transactions import CurrentSession
from insumap.infrastructure.persistence.treatment_orm import TreatmentPlanOrm
from insumap.shared.errors import ErrorCode, InsumapError

ACTIVE: Final = "ACTIVE"
ADULT_POPULATION: Final = "ADULT"
POPULATION_BY_DIABETES_TYPE: Final = {"GDM": "PREGNANCY_T2D_GDM"}
"""Population of the default target profile by ``clinic.patients.diabetes_type``.

The documents say the diabetes type "selects the population" but do not list the
mapping; every type not listed here uses ``ADULT_POPULATION`` (API.md, G-gap).
"""


@final
class ValidationSettingsRepository(ValidationSettingsPort):
    """The active ``care.reading_validation_settings`` of a clinic (or the seed)."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def active_for(self, clinic_id: UUID) -> ValidationParams:
        orm = ReadingValidationSettingsOrm
        row = (
            self._current.get()
            .execute(
                select(orm)
                .where(
                    orm.status == ACTIVE,
                    (orm.clinic_id == clinic_id) | orm.clinic_id.is_(None),
                )
                .order_by(orm.clinic_id.is_(None))
                .limit(1)
            )
            .scalar_one_or_none()
        )
        if row is None:
            raise InsumapError(ErrorCode.INTERNAL_ERROR)
        return ValidationParams(
            min_mg_dl=row.min_measurable_mg_dl,
            max_mg_dl=row.max_measurable_mg_dl,
            future_tolerance=timedelta(seconds=row.future_tolerance_seconds),
            max_age=timedelta(hours=row.max_reading_age_hours),
            duplicate_window=timedelta(seconds=row.duplicate_window_seconds),
            max_rate_mg_dl_per_min=row.max_rate_mg_dl_per_min,
            unit_mismatch_ratio=row.unit_mismatch_ratio,
        )


@final
class SymptomCatalogRepository(SymptomCatalogPort):
    """``care.symptom_catalog``: the clinic entry wins over the global one."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def find_active(self, clinic_id: UUID, code: str) -> SymptomEntry | None:
        orm = SymptomCatalogOrm
        row = (
            self._current.get()
            .execute(
                select(orm)
                .where(
                    orm.code == code,
                    orm.is_active.is_(True),
                    (orm.clinic_id == clinic_id) | orm.clinic_id.is_(None),
                )
                .order_by(orm.clinic_id.is_(None))
                .limit(1)
            )
            .scalar_one_or_none()
        )
        if row is None:
            return None
        return SymptomEntry(symptom_id=row.id, code=row.code, is_alarm=row.is_alarm)


@final
class ActivePlanRepository(ActivePlanPort):
    """The active ``care.treatment_plans`` row of a patient."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def active_plan_id(self, patient_id: UUID) -> UUID | None:
        return (
            self._current.get()
            .execute(
                select(TreatmentPlanOrm.id)
                .where(
                    TreatmentPlanOrm.patient_id == patient_id,
                    TreatmentPlanOrm.status == ACTIVE,
                )
                .limit(1)
            )
            .scalar_one_or_none()
        )
