"""Ports of the metrics: the target profile of a patient and its glucose series."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from insumap.domain.metrics.target_profile import PatientTargets
from insumap.domain.metrics.window import GlucosePoint


class TargetProfilePort(ABC):
    """``care.target_profiles`` through ``care.patient_target_assignments``."""

    @abstractmethod
    def for_patient(self, patient_id: UUID) -> PatientTargets | None:
        """The assigned profile, or the default of the population of the patient."""


class GlucoseSeriesPort(ABC):
    """The current readings of a patient (not superseded, not annulled)."""

    @abstractmethod
    def points(
        self, patient_id: UUID, start: datetime, end: datetime
    ) -> Sequence[GlucosePoint]:
        """Points with ``start <= measured_at < end``, oldest first."""
