"""Risk of glycemic deterioration (IA2): the scoring strategy and its rules fallback.

Pattern: P19 Strategy. ``RiskScoringStrategy`` is the contract; the service
(logistic or gradient boosting) and ``RuleBasedRiskStrategy`` (TIDE-like flags)
are the two strategies. The rules only read the thresholds of the patient's
target profile (``care.target_profiles``): no clinical number is written here.

The rules score is an ordinal count of the targets that are missed, not a
calibrated probability. The tier is read from that count, so ``calibrated`` is
``False`` on every output of this strategy (Contrato-IA 8.2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Final, final, override

PROBABILITY_STEP: Final = Decimal("0.0001")
"""The stored probability keeps four decimals (``numeric(5,4)``)."""
CONTRIBUTION_STEP: Final = Decimal("0.01")


class AssessmentType(StrEnum):
    """What the assessment is for (``ai.risk_assessments.assessment_type``)."""

    DETERIORATION = "DETERIORATION"
    DROPOUT = "DROPOUT"


class RiskTier(StrEnum):
    """The ordinal tier of a risk (``ai.risk_assessments.risk_tier``)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


TIER_BY_BREACHES = (RiskTier.LOW, RiskTier.MEDIUM, RiskTier.HIGH, RiskTier.CRITICAL)
"""Index = number of targets missed, capped at the last tier (ordinal scale)."""


class FactorDirection(StrEnum):
    """Which way a factor pushes the risk (Modulo-IA 5)."""

    INCREASES_RISK = "INCREASES_RISK"
    DECREASES_RISK = "DECREASES_RISK"
    NEUTRAL = "NEUTRAL"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskFeatures:
    """The numbers of the window that the strategies read. ``None`` means no data."""

    data_sufficiency_pct: Decimal | None
    tir_pct: Decimal | None = None
    tbr_l1_pct: Decimal | None = None
    tbr_l2_pct: Decimal | None = None
    tar_l1_pct: Decimal | None = None
    tar_l2_pct: Decimal | None = None
    cv_pct: Decimal | None = None
    mean_glucose_mg_dl: Decimal | None = None
    gmi_pct: Decimal | None = None
    hypo_events_count: int | None = None
    tir_delta_vs_prior_pct: Decimal | None = None
    readings_per_day_avg: Decimal | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskLimits:
    """The targets of the patient's profile, read from the database."""

    tir_min_pct: Decimal
    tbr_l1_max_pct: Decimal
    tbr_l2_max_pct: Decimal
    tar_l1_max_pct: Decimal
    tar_l2_max_pct: Decimal
    cv_max_pct: Decimal
    min_data_sufficiency_pct: Decimal


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskFactor:
    """One factor of the explanation the doctor reads."""

    name: str
    direction: FactorDirection
    value: Decimal
    unit: str | None
    contribution: Decimal


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class RiskScore:
    """What a strategy says. Without enough data there is no probability or tier."""

    is_sufficient: bool
    probability: Decimal | None = None
    tier: RiskTier | None = None
    evaluated: int = 0
    breaches: int = 0
    factors: tuple[RiskFactor, ...] = ()


class RiskScoringStrategy(ABC):
    """How a risk is scored: the service or the rules.

    Pattern: P19 Strategy
    """

    @abstractmethod
    def score(self, features: RiskFeatures, limits: RiskLimits) -> RiskScore:
        """The score of the window, or ``is_sufficient=False`` without data."""


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class _Rule:
    name: str
    value: Decimal | None
    limit: Decimal
    breach_below: bool
    unit: str


@final
class RuleBasedRiskStrategy(RiskScoringStrategy):
    """Counts the targets missed in the window (TIDE-like flags).

    Pattern: P19 Strategy. A rule without its feature is not evaluated; the
    score is the share of evaluated targets that are missed.
    """

    @override
    def score(self, features: RiskFeatures, limits: RiskLimits) -> RiskScore:
        sufficiency = features.data_sufficiency_pct
        if sufficiency is None or sufficiency < limits.min_data_sufficiency_pct:
            return RiskScore(is_sufficient=False)
        rules = _rules(features, limits)
        evaluated = [rule for rule in rules if rule.value is not None]
        if not evaluated:
            return RiskScore(is_sufficient=False)
        missed = [rule for rule in evaluated if _missed(rule)]
        probability = (Decimal(len(missed)) / Decimal(len(evaluated))).quantize(
            PROBABILITY_STEP, rounding=ROUND_HALF_UP
        )
        return RiskScore(
            is_sufficient=True,
            probability=probability,
            tier=TIER_BY_BREACHES[min(len(missed), len(TIER_BY_BREACHES) - 1)],
            evaluated=len(evaluated),
            breaches=len(missed),
            factors=_factors(evaluated, missed),
        )


def _rules(features: RiskFeatures, limits: RiskLimits) -> tuple[_Rule, ...]:
    return (
        _Rule(
            name="tir_pct",
            value=features.tir_pct,
            limit=limits.tir_min_pct,
            breach_below=True,
            unit="%",
        ),
        _Rule(
            name="tbr_l1_pct",
            value=features.tbr_l1_pct,
            limit=limits.tbr_l1_max_pct,
            breach_below=False,
            unit="%",
        ),
        _Rule(
            name="tbr_l2_pct",
            value=features.tbr_l2_pct,
            limit=limits.tbr_l2_max_pct,
            breach_below=False,
            unit="%",
        ),
        _Rule(
            name="tar_l1_pct",
            value=features.tar_l1_pct,
            limit=limits.tar_l1_max_pct,
            breach_below=False,
            unit="%",
        ),
        _Rule(
            name="tar_l2_pct",
            value=features.tar_l2_pct,
            limit=limits.tar_l2_max_pct,
            breach_below=False,
            unit="%",
        ),
        _Rule(
            name="cv_pct",
            value=features.cv_pct,
            limit=limits.cv_max_pct,
            breach_below=False,
            unit="%",
        ),
    )


def _missed(rule: _Rule) -> bool:
    if rule.value is None:
        return False
    return rule.value < rule.limit if rule.breach_below else rule.value > rule.limit


def _factors(evaluated: list[_Rule], missed: list[_Rule]) -> tuple[RiskFactor, ...]:
    """Each missed target is a factor; with none, one neutral factor says so."""
    if not missed:
        first = evaluated[0]
        return (
            RiskFactor(
                name=first.name,
                direction=FactorDirection.NEUTRAL,
                value=first.value or Decimal(0),
                unit=first.unit,
                contribution=Decimal(0),
            ),
        )
    share = (Decimal(1) / Decimal(len(missed))).quantize(
        CONTRIBUTION_STEP, rounding=ROUND_HALF_UP
    )
    return tuple(
        RiskFactor(
            name=rule.name,
            direction=FactorDirection.INCREASES_RISK,
            value=rule.value or Decimal(0),
            unit=rule.unit,
            contribution=share,
        )
        for rule in missed
    )
