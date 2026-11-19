"""Triage of the assigned patients: flags with their reason and a rule-based tier.

Pure domain. The clinical judgement (is the time in range below the goal of the
profile?) comes from the target profile stored in the database and from the
glycemic strategy; this module only turns those answers into flags and orders
the list. The tier is rule based and marked as fallback: no AI score is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID


class TriageFlag(StrEnum):
    """Why a patient needs attention; each flag has its text in ``messages_es``."""

    BELOW_TARGET = "BELOW_TARGET"
    OPEN_ALERTS = "OPEN_ALERTS"
    NO_RECENT_READINGS = "NO_RECENT_READINGS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RiskTier(StrEnum):
    """Tier of the rule-based risk (same names as ``ai.risk_assessments``)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


MEDIUM_FROM_FLAGS: Final = 1
"""One flag is a medium tier; two or more are high."""
HIGH_FROM_FLAGS: Final = 2
NO_ALERTS: Final = 0


def triage_flags(
    *,
    has_readings: bool,
    is_sufficient: bool,
    on_target: bool | None,
    open_alerts: int,
) -> tuple[TriageFlag, ...]:
    """The flags of one patient, in a fixed order.

    ``on_target`` is ``None`` when the strategy cannot judge the window; only an
    explicit ``False`` raises ``BELOW_TARGET``.
    """
    flags: list[TriageFlag] = []
    if not has_readings:
        flags.append(TriageFlag.NO_RECENT_READINGS)
    elif not is_sufficient:
        flags.append(TriageFlag.INSUFFICIENT_DATA)
    if on_target is False:
        flags.append(TriageFlag.BELOW_TARGET)
    if open_alerts > NO_ALERTS:
        flags.append(TriageFlag.OPEN_ALERTS)
    return tuple(flags)


def is_review_current(reviewed_at: datetime, last_reading_at: datetime | None) -> bool:
    """A review holds until a reading arrives after it (the situation changed)."""
    return last_reading_at is None or reviewed_at >= last_reading_at


@dataclass(frozen=True, slots=True, kw_only=True)
class TriageReview:
    """A doctor marked a patient as reviewed (``care.triage_reviews``, append only)."""

    id: UUID
    clinic_id: UUID
    patient_id: UUID
    reviewed_by: UUID
    window_days: int
    reviewed_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class TriageAssessment:
    """One assigned patient in the triage list, with what the doctor needs to see."""

    patient_id: UUID
    full_name: str
    flags: tuple[TriageFlag, ...]
    open_alerts_count: int
    tir_pct: Decimal | None
    last_reading_mg_dl: Decimal | None
    last_reading_at: datetime | None
    reviewed_at: datetime | None

    @property
    def score(self) -> int:
        """Provisional score: the number of active flags."""
        return len(self.flags)

    @property
    def risk_tier(self) -> RiskTier:
        if self.score >= HIGH_FROM_FLAGS:
            return RiskTier.HIGH
        if self.score >= MEDIUM_FROM_FLAGS:
            return RiskTier.MEDIUM
        return RiskTier.LOW

    @property
    def reviewed(self) -> bool:
        """``True`` while the last review is still current."""
        return self.reviewed_at is not None and is_review_current(
            self.reviewed_at, self.last_reading_at
        )

    def sort_key(self) -> tuple[bool, int, bool, Decimal, int, str]:
        """Unreviewed first, then higher score, lower TIR and more open alerts."""
        tir = self.tir_pct if self.tir_pct is not None else Decimal(0)
        return (
            self.reviewed,
            -self.score,
            self.tir_pct is None,
            tir,
            -self.open_alerts_count,
            str(self.patient_id),
        )
