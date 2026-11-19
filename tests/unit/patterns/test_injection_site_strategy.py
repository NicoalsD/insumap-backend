"""P19 Strategy: the injection site rule sits behind an interface and is swappable."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import override

import pytest

from insumap.domain.monitoring.injection_rule import (
    RULES_VERSION,
    InjectionPatientProfile,
    InjectionRuleInput,
    InjectionRulesV1Strategy,
    InjectionSites,
    InjectionSiteStrategy,
)
from insumap.domain.monitoring.injection_sites import PregnancyStatus, SiteCode
from insumap.domain.monitoring.records import InsulinKind
from insumap.domain.onboarding.vocabulary import Sex

NOW = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
INPUT = InjectionRuleInput(
    kind=InsulinKind.BASAL,
    now=NOW,
    profile=InjectionPatientProfile(
        sex=Sex.FEMALE,
        birth_date=None,
        bmi=Decimal(24),
        pregnancy=PregnancyStatus.NONE,
    ),
    plan=None,
    history=(),
)


class FixedSiteStrategy(InjectionSiteStrategy):
    """A different rule: a caller can swap it without any change."""

    @property
    @override
    def rules_version(self) -> str:
        return "fixed-1"

    @override
    def suggest(self, rule_input: InjectionRuleInput) -> InjectionSites:
        return InjectionSites(
            kind=rule_input.kind, suggestion=None, sites=(), rules_version="fixed-1"
        )


def test_the_interface_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        InjectionSiteStrategy()  # type: ignore[abstract]


def test_the_rules_strategy_reports_its_version() -> None:
    strategy: InjectionSiteStrategy = InjectionRulesV1Strategy()
    assert strategy.rules_version == RULES_VERSION
    assert strategy.suggest(INPUT).rules_version == strategy.rules_version


def test_two_strategies_answer_the_same_question_differently() -> None:
    strategies: list[InjectionSiteStrategy] = [
        InjectionRulesV1Strategy(),
        FixedSiteStrategy(),
    ]
    answers = [strategy.suggest(INPUT) for strategy in strategies]
    assert answers[0].suggestion is not None
    assert answers[0].suggestion.site is SiteCode.THIGH_RIGHT
    assert answers[1].suggestion is None


def test_the_input_is_not_changed_by_the_rule() -> None:
    before = replace(INPUT)
    InjectionRulesV1Strategy().suggest(INPUT)
    assert before == INPUT
