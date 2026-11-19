"""The target profile of a patient: a versioned row of ``care.target_profiles``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetProfile:
    """Every threshold and target of the metrics. Nothing here is written in code.

    The profile is read from the database through the assignment of the patient
    (or the default of its population) and its ``id`` and ``version`` travel with
    each result, so a historic metric says which targets it used.
    """

    id: UUID
    code: str
    version: int
    population: str
    range_low_mg_dl: Decimal
    range_high_mg_dl: Decimal
    very_low_mg_dl: Decimal
    very_high_mg_dl: Decimal
    tir_min_pct: Decimal
    tbr_l1_max_pct: Decimal
    tbr_l2_max_pct: Decimal
    tar_l1_max_pct: Decimal
    tar_l2_max_pct: Decimal
    cv_max_pct: Decimal
    min_data_sufficiency_pct: Decimal
    min_days: int
    max_gap_minutes: int
    hypo_episode_min_minutes: int
    min_readings_for_cv: int
    min_readings_for_cv_smbg: int
    night_start: time
    night_end: time


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientTargets:
    """The profile that applies to a patient and the zone of its clinic."""

    patient_id: UUID
    profile: TargetProfile
    timezone: str
