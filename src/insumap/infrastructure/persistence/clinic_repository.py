"""``clinic.clinics``: the tenants, under their row level security."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import final, override
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from insumap.application.clinics.ports import ClinicFilter, ClinicRepositoryPort
from insumap.application.common.pagination import Page, PageRequest, build_page
from insumap.domain.clinic.clinic import Clinic, ClinicStatus
from insumap.domain.common.errors import ConflictError
from insumap.infrastructure.persistence.orm import ClinicOrm
from insumap.infrastructure.persistence.transactions import CurrentSession

NAME_INDEX = "ux_clinics_name_lower"
NAME_TAKEN_REASON = "clinic_name_taken"
INITIAL_LOCK_VERSION = 0


def _clinic(row: ClinicOrm) -> Clinic:
    return Clinic(
        clinic_id=row.id,
        name=row.name,
        tax_id=row.tax_id,
        timezone=row.timezone,
        status=ClinicStatus(row.status),
        is_demo=row.is_demo,
        created_at=row.created_at,
        suspended_at=row.suspended_at,
        suspended_reason=row.suspended_reason,
        lock_version=row.lock_version,
    )


@final
class ClinicRepository(ClinicRepositoryPort):
    """Clinics the session may see: a clinic sees itself, the platform all of them."""

    def __init__(self, current: CurrentSession) -> None:
        self._current = current

    @override
    def get(self, clinic_id: UUID) -> Clinic | None:
        row = self._current.get().get(ClinicOrm, clinic_id)
        return None if row is None else _clinic(row)

    @override
    def list_clinics(self, filters: ClinicFilter, page: PageRequest) -> Page[Clinic]:
        statement = select(ClinicOrm).order_by(ClinicOrm.id)
        if page.after is not None:
            statement = statement.where(ClinicOrm.id > page.after)
        if filters.status is not None:
            statement = statement.where(ClinicOrm.status == filters.status.value)
        if filters.is_demo is not None:
            statement = statement.where(ClinicOrm.is_demo.is_(filters.is_demo))
        rows = self._current.get().scalars(statement.limit(page.limit + 1)).all()
        return build_page(
            [_clinic(row) for row in rows],
            limit=page.limit,
            key=lambda clinic: clinic.clinic_id,
        )

    @override
    def add(self, clinic: Clinic) -> None:
        session = self._current.get()
        with _name_clash_as_conflict():
            session.add(
                ClinicOrm(
                    id=clinic.clinic_id,
                    name=clinic.name,
                    tax_id=clinic.tax_id,
                    timezone=clinic.timezone,
                    status=clinic.status.value,
                    suspended_at=None,
                    suspended_reason=None,
                    is_demo=clinic.is_demo,
                    created_at=clinic.created_at,
                    updated_at=clinic.created_at,
                    lock_version=INITIAL_LOCK_VERSION,
                )
            )
            session.flush()

    @override
    def save(self, clinic: Clinic, *, now: datetime) -> None:
        with _name_clash_as_conflict():
            self._current.get().execute(
                update(ClinicOrm)
                .where(ClinicOrm.id == clinic.clinic_id)
                .values(
                    name=clinic.name,
                    tax_id=clinic.tax_id,
                    timezone=clinic.timezone,
                    status=clinic.status.value,
                    suspended_at=clinic.suspended_at,
                    suspended_reason=clinic.suspended_reason,
                    is_demo=clinic.is_demo,
                    updated_at=now,
                    lock_version=ClinicOrm.lock_version + 1,
                )
            )


@contextmanager
def _name_clash_as_conflict() -> Iterator[None]:
    """A repeated clinic name (case insensitive) is a ``409``; other errors pass."""
    try:
        yield
    except IntegrityError as error:
        if NAME_INDEX in str(error.orig):
            raise ConflictError(NAME_TAKEN_REASON) from None
        raise
