"""Inputs of the validation chain. The parameters come from the database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationParams:
    """One row of ``care.reading_validation_settings``; never written in code."""

    min_mg_dl: Decimal
    max_mg_dl: Decimal
    future_tolerance: timedelta
    max_age: timedelta
    duplicate_window: timedelta
    max_rate_mg_dl_per_min: Decimal
    unit_mismatch_ratio: Decimal


@dataclass(frozen=True, slots=True, kw_only=True)
class PreviousReading:
    """The reading just before the candidate, the history the checks compare to."""

    value_mg_dl: Decimal
    measured_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadingCandidate:
    """A reading about to be saved, with what the chain needs to judge it."""

    value_mg_dl: Decimal
    measured_at: datetime
    now: datetime
    params: ValidationParams
    previous: PreviousReading | None = None
