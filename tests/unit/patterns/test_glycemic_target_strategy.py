"""P19 Strategy: how each population is judged, with profiles the test declares."""

from dataclasses import replace
from decimal import Decimal

import pytest

from insumap.domain.metrics.glycemic_metrics import (
    Confidence,
    GlycemicMetrics,
    Signal,
)
from insumap.domain.metrics.target_strategy import (
    AdultStandardTargetStrategy,
    GlycemicTargetStrategy,
    GlycemicTargetStrategyRegistry,
    OlderOrHighRiskTargetStrategy,
    PregnancyTargetStrategy,
)
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.metrics_factories import PROFILE


def metrics(
    *,
    tir: str | None = "75",
    tbr: str = "2",
    tar: str = "23",
    signal: Signal = Signal.CGM,
) -> GlycemicMetrics:
    return GlycemicMetrics(
        signal=signal,
        data_sufficiency_pct=Decimal(90),
        is_sufficient=True,
        confidence=Confidence.NORMAL,
        tir_pct=None if tir is None else Decimal(tir),
        tbr_pct=Decimal(tbr),
        tar_pct=Decimal(tar),
    )


def test_adult_standard_compares_time_in_range_with_the_profile_minimum() -> None:
    strategy = AdultStandardTargetStrategy()
    minimum = PROFILE.tir_min_pct

    assert strategy.is_on_target(metrics(tir=str(minimum)), PROFILE) is True
    assert (
        strategy.is_on_target(metrics(tir=str(minimum - Decimal("0.01"))), PROFILE)
        is False
    )


def test_the_minimum_comes_from_the_profile_not_from_the_strategy() -> None:
    strict = replace(PROFILE, tir_min_pct=Decimal(90))

    assert (
        AdultStandardTargetStrategy().is_on_target(metrics(tir="80"), strict) is False
    )
    assert (
        AdultStandardTargetStrategy().is_on_target(metrics(tir="80"), PROFILE) is True
    )


def test_older_or_high_risk_looks_at_hypoglycemia_first() -> None:
    strategy = OlderOrHighRiskTargetStrategy()
    limit = PROFILE.tbr_l1_max_pct

    # Great time in range does not save a patient with too much time below range.
    assert (
        strategy.is_on_target(metrics(tir="95", tbr=str(limit + 1)), PROFILE) is False
    )
    assert strategy.is_on_target(metrics(tir="95", tbr=str(limit)), PROFILE) is True
    assert strategy.is_on_target(metrics(tir="10", tbr="0"), PROFILE) is False


def test_pregnancy_needs_range_hypoglycemia_and_hyperglycemia_all_inside() -> None:
    strategy = PregnancyTargetStrategy()

    assert strategy.is_on_target(metrics(tir="75", tbr="3", tar="20"), PROFILE) is True
    assert strategy.is_on_target(metrics(tir="75", tbr="3", tar="30"), PROFILE) is False
    assert strategy.is_on_target(metrics(tir="75", tbr="9", tar="20"), PROFILE) is False
    assert strategy.is_on_target(metrics(tir="60", tbr="3", tar="20"), PROFILE) is False


@pytest.mark.parametrize(
    "strategy",
    [
        AdultStandardTargetStrategy(),
        OlderOrHighRiskTargetStrategy(),
        PregnancyTargetStrategy(),
    ],
)
def test_without_a_percentage_signal_the_strategy_cannot_say(
    strategy: GlycemicTargetStrategy,
) -> None:
    assert strategy.is_on_target(metrics(signal=Signal.SMBG), PROFILE) is None
    assert strategy.is_on_target(metrics(tir=None), PROFILE) is None


def test_the_registry_chooses_the_strategy_by_the_population_of_the_profile() -> None:
    registry = GlycemicTargetStrategyRegistry()

    chosen = {
        population: registry.for_profile(replace(PROFILE, population=population)).code
        for population in (
            "ADULT",
            "OLDER_OR_HIGH_RISK",
            "PREGNANCY_T1D",
            "PREGNANCY_T2D_GDM",
        )
    }

    assert chosen == {
        "ADULT": "ADULT_STANDARD",
        "OLDER_OR_HIGH_RISK": "OLDER_OR_HIGH_RISK",
        "PREGNANCY_T1D": "PREGNANCY",
        "PREGNANCY_T2D_GDM": "PREGNANCY",
    }


def test_an_unknown_population_is_an_internal_error() -> None:
    with pytest.raises(InsumapError) as caught:
        GlycemicTargetStrategyRegistry().for_profile(
            replace(PROFILE, population="SOMETHING_ELSE")
        )

    assert caught.value.code is ErrorCode.INTERNAL_ERROR
