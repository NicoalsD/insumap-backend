"""``RuleBasedRiskStrategy`` (P19 Strategy): the TIDE-like rules over the profile
targets."""

from decimal import Decimal

from insumap.domain.ai.risk import (
    FactorDirection,
    RiskFeatures,
    RiskLimits,
    RiskTier,
    RuleBasedRiskStrategy,
)

LIMITS = RiskLimits(
    tir_min_pct=Decimal("70"),
    tbr_l1_max_pct=Decimal("4"),
    tbr_l2_max_pct=Decimal("1"),
    tar_l1_max_pct=Decimal("25"),
    tar_l2_max_pct=Decimal("5"),
    cv_max_pct=Decimal("36"),
    min_data_sufficiency_pct=Decimal("70"),
)
ON_TARGET = RiskFeatures(
    data_sufficiency_pct=Decimal("92"),
    tir_pct=Decimal("80"),
    tbr_l1_pct=Decimal("2"),
    tbr_l2_pct=Decimal("0.2"),
    tar_l1_pct=Decimal("15"),
    tar_l2_pct=Decimal("2"),
    cv_pct=Decimal("30"),
)


def test_every_target_met_is_low_risk_with_a_neutral_factor() -> None:
    score = RuleBasedRiskStrategy().score(ON_TARGET, LIMITS)

    assert score.is_sufficient is True
    assert score.probability == Decimal("0")
    assert score.tier is RiskTier.LOW
    assert score.evaluated == 6
    assert score.breaches == 0
    (factor,) = score.factors
    assert factor.direction is FactorDirection.NEUTRAL
    assert factor.contribution == Decimal("0")


def test_missed_targets_are_the_probability_and_the_factors() -> None:
    features = RiskFeatures(
        data_sufficiency_pct=Decimal("92"),
        tir_pct=Decimal("48"),
        tbr_l1_pct=Decimal("6"),
        tbr_l2_pct=Decimal("0.2"),
        tar_l1_pct=Decimal("15"),
        tar_l2_pct=Decimal("2"),
        cv_pct=Decimal("30"),
    )

    score = RuleBasedRiskStrategy().score(features, LIMITS)

    assert score.breaches == 2
    assert score.probability == Decimal("0.3333")
    assert score.tier is RiskTier.HIGH
    assert {factor.name for factor in score.factors} == {"tir_pct", "tbr_l1_pct"}
    assert all(
        factor.direction is FactorDirection.INCREASES_RISK for factor in score.factors
    )
    assert sum(factor.contribution for factor in score.factors) == Decimal("1.00")


def test_many_missed_targets_cap_at_the_last_tier() -> None:
    features = RiskFeatures(
        data_sufficiency_pct=Decimal("95"),
        tir_pct=Decimal("30"),
        tbr_l1_pct=Decimal("9"),
        tbr_l2_pct=Decimal("3"),
        tar_l1_pct=Decimal("50"),
        tar_l2_pct=Decimal("20"),
        cv_pct=Decimal("50"),
    )

    score = RuleBasedRiskStrategy().score(features, LIMITS)

    assert score.breaches == 6
    assert score.probability == Decimal("1.0000")
    assert score.tier is RiskTier.CRITICAL


def test_insufficient_data_gives_no_score() -> None:
    features = RiskFeatures(data_sufficiency_pct=Decimal("40"), tir_pct=Decimal("10"))

    score = RuleBasedRiskStrategy().score(features, LIMITS)

    assert score.is_sufficient is False
    assert score.probability is None
    assert score.tier is None


def test_a_rule_without_its_feature_is_not_evaluated() -> None:
    features = RiskFeatures(
        data_sufficiency_pct=Decimal("90"),
        tir_pct=Decimal("60"),
        tbr_l1_pct=None,
        tbr_l2_pct=None,
        tar_l1_pct=None,
        tar_l2_pct=None,
        cv_pct=None,
    )

    score = RuleBasedRiskStrategy().score(features, LIMITS)

    assert score.evaluated == 1
    assert score.breaches == 1
    assert score.probability == Decimal("1.0000")


def test_no_evaluable_rule_is_insufficient_even_with_enough_data() -> None:
    features = RiskFeatures(
        data_sufficiency_pct=Decimal("90"),
        tir_pct=None,
        tbr_l1_pct=None,
        tbr_l2_pct=None,
        tar_l1_pct=None,
        tar_l2_pct=None,
        cv_pct=None,
    )

    assert RuleBasedRiskStrategy().score(features, LIMITS).is_sufficient is False
