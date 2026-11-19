"""In-memory doubles of the goals and reminders ports, with the database's rules.

The catalog keeps one active version per clinic and code, the assignments one
open row per patient and the reminders the clinic of their patient, so a test
fails here for the same reason it would fail against PostgreSQL.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import override
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.application.reminders.ports import ReminderRepositoryPort
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
from insumap.domain.reminders.reminder import Reminder
from insumap.infrastructure.targets_adapters import TargetsAdapters

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
CLINIC_ID = UUID(int=9)
ADMIN_ID = UUID(int=3)


def default_values(**overrides: object) -> TargetProfileValues:
    """A consistent set of values. The numbers are fixtures, not clinical rules."""
    base: dict[str, object] = {
        "label": "Perfil de la clínica",
        "population": "ADULT",
        "is_default": False,
        "range_low_mg_dl": Decimal("70.0"),
        "range_high_mg_dl": Decimal("180.0"),
        "very_low_mg_dl": Decimal("54.0"),
        "very_high_mg_dl": Decimal("250.0"),
        "tir_min_pct": Decimal("70.00"),
        "tbr_l1_max_pct": Decimal("4.00"),
        "tbr_l2_max_pct": Decimal("1.00"),
        "tar_l1_max_pct": Decimal("25.00"),
        "tar_l2_max_pct": Decimal("5.00"),
        "cv_max_pct": Decimal("36.00"),
        "min_data_sufficiency_pct": Decimal("70.00"),
        "min_days": 14,
        "max_gap_minutes": 15,
        "hypo_episode_min_minutes": 15,
        "min_readings_for_cv": 100,
        "min_readings_for_cv_smbg": 3,
        "night_start": time(0, 0),
        "night_end": time(6, 0),
        "source_reference": "Fuente de prueba",
    }
    base.update(overrides)
    return TargetProfileValues(**base)  # type: ignore[arg-type]


def clinic_profile(
    profile_id: UUID,
    *,
    code: str = "CLINIC_TARGETS",
    version: int = 1,
    status: str = ACTIVE,
    clinic_id: UUID | None = CLINIC_ID,
    **values: object,
) -> TargetProfileVersion:
    return TargetProfileVersion(
        id=profile_id,
        clinic_id=clinic_id,
        code=code,
        version=version,
        status=status,
        values=default_values(**values),
        created_at=NOW,
        created_by=ADMIN_ID,
        activated_at=NOW,
    )


class FakeTargetCatalog(TargetProfileCatalogPort):
    def __init__(self, *profiles: TargetProfileVersion) -> None:
        self.profiles: dict[UUID, TargetProfileVersion] = {p.id: p for p in profiles}

    @override
    def list_active(
        self, population: str | None, page: PageRequest
    ) -> Page[TargetProfileVersion]:
        rows = sorted(
            (
                p
                for p in self.profiles.values()
                if p.status == ACTIVE
                and (population is None or p.values.population == population)
                and (page.after is None or p.id > page.after)
            ),
            key=lambda p: p.id,
        )
        return build_page(rows[: page.limit + 1], limit=page.limit, key=lambda p: p.id)

    @override
    def get(self, profile_id: UUID) -> TargetProfileVersion | None:
        return self.profiles.get(profile_id)

    @override
    def versions_of(
        self, clinic_id: UUID | None, code: str
    ) -> tuple[TargetProfileVersion, ...]:
        return tuple(
            sorted(
                (
                    p
                    for p in self.profiles.values()
                    if p.code == code and p.clinic_id == clinic_id
                ),
                key=lambda p: p.version,
            )
        )

    @override
    def active_of_clinic(
        self, clinic_id: UUID, code: str
    ) -> TargetProfileVersion | None:
        return next(
            (
                p
                for p in self.profiles.values()
                if p.clinic_id == clinic_id and p.code == code and p.status == ACTIVE
            ),
            None,
        )

    @override
    def code_exists(self, clinic_id: UUID, code: str) -> bool:
        return any(
            p.clinic_id == clinic_id and p.code == code for p in self.profiles.values()
        )

    @override
    def retire(self, profile_id: UUID) -> bool:
        current = self.profiles.get(profile_id)
        if current is None or current.status != ACTIVE:
            return False
        self.profiles[profile_id] = replace(current, status=RETIRED)
        return True

    @override
    def insert(self, version: TargetProfileVersion) -> None:
        if version.status == ACTIVE and self.active_of_clinic(
            version.clinic_id or CLINIC_ID, version.code
        ):
            raise ConflictError(VERSION_RACE if version.version > 1 else CODE_TAKEN)
        self.profiles[version.id] = version


class FakeTargetAssignments(PatientTargetAssignmentPort):
    def __init__(self) -> None:
        self.rows: list[PatientTargetAssignment] = []

    @override
    def open_for_patient(self, patient_id: UUID) -> PatientTargetAssignment | None:
        return next(
            (r for r in self.rows if r.patient_id == patient_id and r.is_open), None
        )

    @override
    def end(self, assignment: PatientTargetAssignment) -> None:
        self.rows = [assignment if r.id == assignment.id else r for r in self.rows]

    @override
    def insert(self, assignment: PatientTargetAssignment) -> None:
        if self.open_for_patient(assignment.patient_id) is not None:
            raise ConflictError("patient_target_conflict")
        self.rows.append(assignment)


class FakeReminders(ReminderRepositoryPort):
    def __init__(self) -> None:
        self.rows: dict[UUID, Reminder] = {}

    @override
    def get(self, reminder_id: UUID) -> Reminder | None:
        return self.rows.get(reminder_id)

    @override
    def list_for_patient(self, patient_id: UUID, page: PageRequest) -> Page[Reminder]:
        rows = sorted(
            (
                r
                for r in self.rows.values()
                if r.patient_id == patient_id
                and (page.after is None or r.id > page.after)
            ),
            key=lambda r: r.id,
        )
        return build_page(rows[: page.limit + 1], limit=page.limit, key=lambda r: r.id)

    @override
    def insert(self, reminder: Reminder) -> None:
        self.rows[reminder.id] = reminder

    @override
    def update(self, reminder: Reminder) -> None:
        self.rows[reminder.id] = reminder


def targets_adapters(
    *,
    catalog: FakeTargetCatalog | None = None,
    assignments: FakeTargetAssignments | None = None,
    reminders: FakeReminders | None = None,
) -> TargetsAdapters:
    return TargetsAdapters(
        catalog=catalog or FakeTargetCatalog(),
        assignments=assignments or FakeTargetAssignments(),
        reminders=reminders or FakeReminders(),
    )
