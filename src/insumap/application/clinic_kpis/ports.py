"""Ports of the clinic KPIs: aggregates the administrator may read under RLS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping


class ClinicKpiPort(ABC):
    """Account status counts and the small-cell setting of the session clinic."""

    @abstractmethod
    def patient_status_counts(self) -> Mapping[str, int]:
        """Patients of the clinic per ``iam.users.status``."""

    @abstractmethod
    def min_cell_size(self) -> int:
        """Counts below this value are not shown (``clinic.clinic_settings``)."""
