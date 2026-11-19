"""In-memory clinic repository; the name is unique ignoring case, as in the DB."""

from __future__ import annotations

from datetime import datetime
from typing import override
from uuid import UUID

from insumap.application.clinics.ports import ClinicFilter, ClinicRepositoryPort
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.clinic.clinic import Clinic
from insumap.domain.common.errors import ConflictError
from insumap.infrastructure.persistence.clinic_repository import NAME_TAKEN_REASON


class FakeClinics(ClinicRepositoryPort):
    def __init__(self, *clinics: Clinic) -> None:
        self.rows: dict[UUID, Clinic] = {c.clinic_id: c for c in clinics}
        self.saved_at: list[datetime] = []

    @override
    def get(self, clinic_id: UUID) -> Clinic | None:
        return self.rows.get(clinic_id)

    @override
    def list_clinics(self, filters: ClinicFilter, page: PageRequest) -> Page[Clinic]:
        rows = sorted(self.rows.values(), key=lambda c: c.clinic_id)
        rows = [
            c
            for c in rows
            if (page.after is None or c.clinic_id > page.after)
            and (filters.status is None or c.status is filters.status)
            and (filters.is_demo is None or c.is_demo is filters.is_demo)
        ]
        return build_page(
            rows[: page.limit + 1], limit=page.limit, key=lambda c: c.clinic_id
        )

    @override
    def add(self, clinic: Clinic) -> None:
        self._ensure_name_free(clinic)
        self.rows[clinic.clinic_id] = clinic

    @override
    def save(self, clinic: Clinic, *, now: datetime) -> None:
        self._ensure_name_free(clinic)
        self.rows[clinic.clinic_id] = clinic
        self.saved_at.append(now)

    def _ensure_name_free(self, clinic: Clinic) -> None:
        taken = any(
            other.clinic_id != clinic.clinic_id
            and other.name.lower() == clinic.name.lower()
            for other in self.rows.values()
        )
        if taken:
            raise ConflictError(NAME_TAKEN_REASON)
