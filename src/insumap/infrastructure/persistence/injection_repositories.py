"""PostgreSQL readers of the injection-site rule: the body profile and the history.

They only select. Every statement runs on the session of the open transaction,
under the RLS context the unit of work set.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import case, func, select

from insumap.application.monitoring.injection import (
    InjectionHistoryPort,
    PatientBodyProfile,
    PatientBodyProfilePort,
)
from insumap.domain.monitoring.injection_rule import (
    InjectionHistoryEntry,
    LipohypertrophyReport,
)
from insumap.domain.monitoring.injection_sites import PregnancyStatus, SiteCode
from insumap.domain.monitoring.records import InsulinKind
from insumap.domain.onboarding.vocabulary import Sex
from insumap.infrastructure.persistence.monitoring_orm import (
    InsulinDoseOrm,
    SymptomCatalogOrm,
    SymptomOrm,
)
from insumap.infrastructure.persistence.monitoring_repositories import is_current
from insumap.infrastructure.persistence.orm import PatientOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

LIPOHYPERTROPHY_CODE = "LIPOHYPERTROPHY"
BASAL = InsulinKind.BASAL.value
BASAL_FAMILY = "BASAL"
RAPID_FAMILY = "RAPID"


@final
class PatientBodyProfileRepository(PatientBodyProfilePort):
    """``clinic.patients``: sex, birth date, BMI and pregnancy status."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def for_patient(self, patient_id: UUID) -> PatientBodyProfile | None:
        row = (
            self._current.get()
            .execute(
                select(
                    PatientOrm.sex,
                    PatientOrm.birth_date,
                    PatientOrm.bmi,
                    PatientOrm.pregnancy_status,
                ).where(PatientOrm.id == patient_id)
            )
            .one_or_none()
        )
        if row is None:
            return None
        return PatientBodyProfile(
            sex=Sex(row.sex),
            birth_date=row.birth_date,
            bmi=row.bmi,
            pregnancy_status=PregnancyStatus(row.pregnancy_status),
        )


@final
class InjectionHistoryRepository(InjectionHistoryPort):
    """Doses with a site (``monitoring.insulin_doses``) and lipohypertrophy symptoms."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def latest_by_site(self, patient_id: UUID) -> Sequence[InjectionHistoryEntry]:
        orm = InsulinDoseOrm
        family = case((orm.insulin_kind == BASAL, BASAL_FAMILY), else_=RAPID_FAMILY)
        ranked = (
            select(
                orm.injection_site,
                orm.injection_spot,
                orm.insulin_kind,
                orm.administered_at,
                func.row_number()
                .over(
                    partition_by=(orm.injection_site, family),
                    order_by=(orm.administered_at.desc(), orm.id.desc()),
                )
                .label("position"),
            )
            .where(
                orm.patient_id == patient_id,
                orm.injection_site.is_not(None),
                is_current(orm),
            )
            .subquery()
        )
        rows = self._current.get().execute(select(ranked).where(ranked.c.position == 1))
        return [
            InjectionHistoryEntry(
                site=SiteCode(row.injection_site),
                spot=row.injection_spot,
                kind=InsulinKind(row.insulin_kind),
                administered_at=row.administered_at,
            )
            for row in rows
        ]

    @override
    def lipohypertrophy_since(
        self, patient_id: UUID, since: datetime
    ) -> Sequence[LipohypertrophyReport]:
        orm = SymptomOrm
        catalog = SymptomCatalogOrm
        rows = self._current.get().execute(
            select(orm.injection_site, orm.occurred_at)
            .join(catalog, catalog.id == orm.symptom_id)
            .where(
                orm.patient_id == patient_id,
                catalog.code == LIPOHYPERTROPHY_CODE,
                orm.injection_site.is_not(None),
                orm.occurred_at >= since,
                is_current(orm),
            )
        )
        return [
            LipohypertrophyReport(
                site=SiteCode(row.injection_site), reported_at=row.occurred_at
            )
            for row in rows
        ]
