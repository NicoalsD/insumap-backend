"""Ports of the clinic use cases: the tenant rows under row level security."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from insumap.application.common.pagination import Page, PageRequest
from insumap.domain.clinic.clinic import Clinic, ClinicStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ClinicFilter:
    """Filters of ``GET /clinics`` (all optional)."""

    status: ClinicStatus | None = None
    is_demo: bool | None = None


class ClinicRepositoryPort(ABC):
    """Clinics (``clinic.clinics``), read and written under row level security."""

    @abstractmethod
    def get(self, clinic_id: UUID) -> Clinic | None:
        """One clinic, or ``None`` if the session cannot see it."""

    @abstractmethod
    def list_clinics(self, filters: ClinicFilter, page: PageRequest) -> Page[Clinic]:
        """A page of clinics, oldest identifier first."""

    @abstractmethod
    def add(self, clinic: Clinic) -> None:
        """Insert a new clinic; a repeated name raises ``ConflictError``."""

    @abstractmethod
    def save(self, clinic: Clinic, *, now: datetime) -> None:
        """Persist the state of an existing clinic and bump its lock version."""
