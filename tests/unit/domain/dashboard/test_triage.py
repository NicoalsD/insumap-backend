"""Triage rules: flags, the rule-based tier and the review that expires."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from insumap.domain.dashboard.triage import (
    RiskTier,
    TriageAssessment,
    TriageFlag,
    is_review_current,
    triage_flags,
)
from tests.support.monitoring_factories import NOW

PATIENT = UUID(int=0xA1)


def assessment(
    flags: tuple[TriageFlag, ...] = (),
    *,
    tir: str | None = "70",
    alerts: int = 0,
    reviewed_at: datetime | None = None,
    last_reading_at: datetime | None = None,
) -> TriageAssessment:
    return TriageAssessment(
        patient_id=PATIENT,
        full_name="Paciente",
        flags=flags,
        open_alerts_count=alerts,
        tir_pct=None if tir is None else Decimal(tir),
        last_reading_mg_dl=None,
        last_reading_at=last_reading_at,
        reviewed_at=reviewed_at,
    )


def test_no_readings_is_flagged_and_not_judged_as_insufficient() -> None:
    flags = triage_flags(
        has_readings=False, is_sufficient=False, on_target=None, open_alerts=0
    )

    assert flags == (TriageFlag.NO_RECENT_READINGS,)


def test_too_few_readings_is_insufficient_data() -> None:
    flags = triage_flags(
        has_readings=True, is_sufficient=False, on_target=None, open_alerts=0
    )

    assert flags == (TriageFlag.INSUFFICIENT_DATA,)


def test_only_an_explicit_off_target_raises_below_target() -> None:
    unknown = triage_flags(
        has_readings=True, is_sufficient=True, on_target=None, open_alerts=0
    )
    off = triage_flags(
        has_readings=True, is_sufficient=True, on_target=False, open_alerts=0
    )

    assert TriageFlag.BELOW_TARGET not in unknown
    assert TriageFlag.BELOW_TARGET in off


def test_open_alerts_add_their_flag_in_a_fixed_order() -> None:
    flags = triage_flags(
        has_readings=True, is_sufficient=True, on_target=False, open_alerts=1
    )

    assert flags == (TriageFlag.BELOW_TARGET, TriageFlag.OPEN_ALERTS)


def test_the_tier_follows_the_number_of_flags() -> None:
    assert assessment().risk_tier is RiskTier.LOW
    assert assessment((TriageFlag.OPEN_ALERTS,)).risk_tier is RiskTier.MEDIUM
    assert (
        assessment((TriageFlag.OPEN_ALERTS, TriageFlag.BELOW_TARGET)).risk_tier
        is RiskTier.HIGH
    )


def test_a_review_holds_until_a_newer_reading_arrives() -> None:
    reviewed = NOW
    assert is_review_current(reviewed, None)
    assert is_review_current(reviewed, NOW - timedelta(hours=1))
    assert not is_review_current(reviewed, NOW + timedelta(minutes=1))


def test_the_list_puts_unreviewed_patients_first() -> None:
    reviewed = assessment((TriageFlag.OPEN_ALERTS,), reviewed_at=NOW)
    pending = assessment((), reviewed_at=None)

    ordered = sorted([reviewed, pending], key=TriageAssessment.sort_key)

    assert ordered == [pending, reviewed]
