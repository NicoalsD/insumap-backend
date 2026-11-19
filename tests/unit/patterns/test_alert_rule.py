"""P08 Composite: alert rule trees evaluate from data, never from literals."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from insumap.domain.alerts.rules import (
    AllOfRule,
    AnyOfRule,
    Comparator,
    DurationRule,
    GlucoseEvidence,
    RateDirection,
    RateOfChangeRule,
    ThresholdRule,
    parse_rule_definition,
)
from insumap.domain.metrics.window import GlucosePoint
from insumap.shared.errors import InsumapError

T0 = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


def point(minutes: int, mg_dl: str) -> GlucosePoint:
    return GlucosePoint(at=T0 + timedelta(minutes=minutes), mg_dl=Decimal(mg_dl))


def evidence(*points: GlucosePoint) -> GlucoseEvidence:
    return GlucoseEvidence(current=points[-1], history=tuple(points))


def test_threshold_compares_the_triggering_reading() -> None:
    rule = ThresholdRule(comparator=Comparator.LT, value_mg_dl=Decimal(70))

    assert rule.matches(evidence(point(0, "65")))
    assert not rule.matches(evidence(point(0, "70")))


def test_duration_needs_the_whole_span_below_the_threshold() -> None:
    rule = DurationRule(
        comparator=Comparator.LT, value_mg_dl=Decimal(70), lasting=timedelta(minutes=15)
    )

    held = evidence(point(-20, "60"), point(-10, "65"), point(0, "62"))
    broken = evidence(point(-20, "60"), point(-10, "90"), point(0, "62"))

    assert rule.matches(held)
    assert not rule.matches(broken)


def test_duration_uses_the_reading_in_effect_at_the_start_of_the_span() -> None:
    rule = DurationRule(
        comparator=Comparator.LT, value_mg_dl=Decimal(70), lasting=timedelta(minutes=15)
    )

    # The span is (-15, 0]: the reading in effect at -15 is the one at -20.
    assert rule.matches(evidence(point(-20, "60"), point(-5, "66"), point(0, "68")))
    assert not rule.matches(evidence(point(-20, "80"), point(-5, "66"), point(0, "68")))


def test_duration_without_any_reading_at_the_start_does_not_match() -> None:
    rule = DurationRule(
        comparator=Comparator.LT, value_mg_dl=Decimal(70), lasting=timedelta(minutes=15)
    )

    assert not rule.matches(evidence(point(-5, "60"), point(0, "60")))


def test_rate_of_change_compares_with_the_previous_reading_in_span() -> None:
    rule = RateOfChangeRule(
        direction=RateDirection.FALLING,
        mg_dl_per_min=Decimal(2),
        within=timedelta(minutes=15),
    )

    assert rule.matches(evidence(point(-10, "120"), point(0, "95")))
    assert not rule.matches(evidence(point(-10, "120"), point(0, "110")))


def test_all_of_needs_every_child_and_any_of_one() -> None:
    low = ThresholdRule(comparator=Comparator.LT, value_mg_dl=Decimal(70))
    falling = RateOfChangeRule(
        direction=RateDirection.FALLING,
        mg_dl_per_min=Decimal(2),
        within=timedelta(minutes=15),
    )
    reading = evidence(point(-10, "120"), point(0, "65"))

    assert AllOfRule([low, falling]).matches(reading)
    assert AnyOfRule(
        [low, ThresholdRule(comparator=Comparator.GT, value_mg_dl=Decimal(300))]
    ).matches(reading)
    assert not AllOfRule(
        [low, ThresholdRule(comparator=Comparator.GT, value_mg_dl=Decimal(300))]
    ).matches(reading)


def test_parses_a_nested_definition_from_data() -> None:
    definition = {
        "op": "ALL_OF",
        "children": [
            {"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": 70},
            {
                "op": "ANY_OF",
                "children": [
                    {
                        "kind": "DURATION",
                        "comparator": "LT",
                        "value_mg_dl": 80,
                        "minutes": 15,
                    },
                    {
                        "kind": "RATE_OF_CHANGE",
                        "direction": "FALLING",
                        "mg_dl_per_min": 2,
                        "within_minutes": 15,
                    },
                ],
            },
        ],
    }

    node = parse_rule_definition(definition)

    assert isinstance(node, AllOfRule)
    assert node.lookback() == timedelta(minutes=15)
    assert node.matches(evidence(point(-10, "120"), point(0, "65")))


@pytest.mark.parametrize(
    "definition",
    [
        {},
        {"kind": "THRESHOLD", "comparator": "LT"},
        {"kind": "THRESHOLD", "comparator": "EQ", "value_mg_dl": 70},
        {"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": 70, "extra": 1},
        {"kind": "DURATION", "comparator": "LT", "value_mg_dl": 70, "minutes": 0},
        {"kind": "DURATION", "comparator": "LT", "value_mg_dl": 70, "minutes": True},
        {
            "kind": "RATE_OF_CHANGE",
            "direction": "SIDEWAYS",
            "mg_dl_per_min": 2,
            "within_minutes": 15,
        },
        {"op": "ALL_OF", "children": []},
        {
            "op": "XOR",
            "children": [{"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": 70}],
        },
        {"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": "NaN"},
    ],
)
def test_refuses_malformed_definitions(definition: dict[str, object]) -> None:
    with pytest.raises(InsumapError):
        parse_rule_definition(definition)


def test_refuses_a_tree_deeper_than_the_limit() -> None:
    node: dict[str, object] = {
        "kind": "THRESHOLD",
        "comparator": "LT",
        "value_mg_dl": 70,
    }
    for _ in range(6):
        node = {"op": "ALL_OF", "children": [node]}

    with pytest.raises(InsumapError):
        parse_rule_definition(node)
