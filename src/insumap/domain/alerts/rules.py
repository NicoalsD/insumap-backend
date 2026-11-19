"""Alert rules as composite trees (P08): thresholds, durations and rates are data.

A condition is stored as jsonb in ``alerts.alert_rules.definition``. Its nodes:

- ``{"kind": "THRESHOLD", "comparator": "LT", "value_mg_dl": 70}``: the reading
  that triggered the evaluation satisfies the comparison.
- ``{"kind": "DURATION", "comparator": "LT", "value_mg_dl": 70, "minutes": 15}``:
  the comparison held for the whole last ``minutes``. The reading in effect at the
  start of that span (the latest one at or before it) must satisfy it, and so must
  every reading after it up to the triggering one.
- ``{"kind": "RATE_OF_CHANGE", "direction": "FALLING", "mg_dl_per_min": 2,
  "within_minutes": 15}``: against the last earlier reading within the span, the
  glucose moved at that rate or faster in that direction.
- ``{"op": "ALL_OF" | "ANY_OF", "children": [...]}``: a group of nodes.

Nothing clinical is written in this module: every threshold, duration and rate
comes from the definition read from the database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final, assert_never, final, override

from insumap.domain.metrics.window import GlucosePoint, elapsed_minutes
from insumap.shared.errors import ErrorCode, InsumapError
from insumap.shared.field_limits import FieldLimits

KIND: Final = "kind"
OP: Final = "op"
CHILDREN: Final = "children"
COMPARATOR: Final = "comparator"
VALUE: Final = "value_mg_dl"
MINUTES: Final = "minutes"
DIRECTION: Final = "direction"
RATE: Final = "mg_dl_per_min"
WITHIN: Final = "within_minutes"


class Comparator(StrEnum):
    """How a reading is compared with a threshold."""

    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"

    def holds(self, value: Decimal, threshold: Decimal) -> bool:
        """Whether ``value`` is on the side of ``threshold`` this comparator names."""
        match self:
            case Comparator.LT:
                return value < threshold
            case Comparator.LTE:
                return value <= threshold
            case Comparator.GT:
                return value > threshold
            case Comparator.GTE:
                return value >= threshold
            case _:
                assert_never(self)


class RateDirection(StrEnum):
    """Which way the glucose must move for a rate rule to hold."""

    FALLING = "FALLING"
    RISING = "RISING"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class GlucoseEvidence:
    """What a rule reads: the triggering reading and the history around it.

    ``history`` is ascending by time and ends with ``current``. Its first point may
    be older than any span a rule looks at: it is the reading in effect before the
    span starts.
    """

    current: GlucosePoint
    history: tuple[GlucosePoint, ...]

    def effective_at(self, instant: datetime) -> GlucosePoint | None:
        """The reading in effect at ``instant``: the latest one at or before it."""
        found: GlucosePoint | None = None
        for point in self.history:
            if point.at > instant:
                break
            found = point
        return found

    def between(self, start: datetime, end: datetime) -> tuple[GlucosePoint, ...]:
        """The readings with ``start < at <= end``."""
        return tuple(point for point in self.history if start < point.at <= end)


class AlertRuleNode(ABC):
    """Component of the composite: a leaf condition or a group of conditions.

    Pattern: P08 Composite
    """

    @abstractmethod
    def matches(self, evidence: GlucoseEvidence) -> bool:
        """Whether the condition holds for the triggering reading."""

    @abstractmethod
    def lookback(self) -> timedelta:
        """How far before the triggering reading the condition reads."""


@final
class ThresholdRule(AlertRuleNode):
    """The triggering reading is on the side of the threshold."""

    def __init__(self, *, comparator: Comparator, value_mg_dl: Decimal) -> None:
        self._comparator = comparator
        self._value = value_mg_dl

    @override
    def matches(self, evidence: GlucoseEvidence) -> bool:
        return self._comparator.holds(evidence.current.mg_dl, self._value)

    @override
    def lookback(self) -> timedelta:
        return timedelta(0)


@final
class DurationRule(AlertRuleNode):
    """The comparison held for the whole last ``lasting`` (see the module doc)."""

    def __init__(
        self, *, comparator: Comparator, value_mg_dl: Decimal, lasting: timedelta
    ) -> None:
        self._comparator = comparator
        self._value = value_mg_dl
        self._lasting = lasting

    @override
    def matches(self, evidence: GlucoseEvidence) -> bool:
        current = evidence.current
        since = current.at - self._lasting
        anchor = evidence.effective_at(since)
        if anchor is None or not self._comparator.holds(anchor.mg_dl, self._value):
            return False
        return all(
            self._comparator.holds(point.mg_dl, self._value)
            for point in evidence.between(since, current.at)
        )

    @override
    def lookback(self) -> timedelta:
        return self._lasting


@final
class RateOfChangeRule(AlertRuleNode):
    """The glucose moved at ``mg_dl_per_min`` or faster in ``direction``."""

    def __init__(
        self,
        *,
        direction: RateDirection,
        mg_dl_per_min: Decimal,
        within: timedelta,
    ) -> None:
        self._direction = direction
        self._rate = mg_dl_per_min
        self._within = within

    @override
    def matches(self, evidence: GlucoseEvidence) -> bool:
        current = evidence.current
        since = current.at - self._within
        earlier = [
            point for point in evidence.history if since <= point.at < current.at
        ]
        if not earlier:
            return False
        previous = earlier[-1]
        minutes = elapsed_minutes(previous.at, current.at)
        if minutes <= 0:
            return False
        match self._direction:
            case RateDirection.FALLING:
                change = previous.mg_dl - current.mg_dl
            case RateDirection.RISING:
                change = current.mg_dl - previous.mg_dl
            case _:
                assert_never(self._direction)
        return change / minutes >= self._rate

    @override
    def lookback(self) -> timedelta:
        return self._within


class _Group(AlertRuleNode):
    def __init__(self, children: Sequence[AlertRuleNode]) -> None:
        self._children = tuple(children)

    @override
    def lookback(self) -> timedelta:
        return max(child.lookback() for child in self._children)


@final
class AllOfRule(_Group):
    """Every child holds."""

    @override
    def matches(self, evidence: GlucoseEvidence) -> bool:
        return all(child.matches(evidence) for child in self._children)


@final
class AnyOfRule(_Group):
    """At least one child holds."""

    @override
    def matches(self, evidence: GlucoseEvidence) -> bool:
        return any(child.matches(evidence) for child in self._children)


def invalid_rule(issue: str) -> InsumapError:
    """A rule definition that cannot be used; the field is the one the body sent."""
    return InsumapError(
        ErrorCode.VALIDATION_ERROR,
        detail={"errors": [{"field": "body.condition", "type": issue}]},
    )


@final
class _NodeCounter:
    def __init__(self) -> None:
        self.count = 0


def parse_rule_definition(raw: Mapping[str, object]) -> AlertRuleNode:
    """Build the composite of a stored or requested definition, or refuse it.

    Depth, node count and every value are checked here, so a definition that
    reaches the evaluator is always well formed.
    """
    return _parse(raw, depth=1, counter=_NodeCounter())


def _parse(raw: object, *, depth: int, counter: _NodeCounter) -> AlertRuleNode:
    if not isinstance(raw, Mapping):
        raise invalid_rule("invalid_node")
    if depth > FieldLimits.ALERT_CONDITION_MAX_DEPTH:
        raise invalid_rule("too_deep")
    counter.count += 1
    if counter.count > FieldLimits.ALERT_CONDITION_MAX_NODES:
        raise invalid_rule("too_many_nodes")
    if OP in raw:
        return _group(raw, depth=depth, counter=counter)
    kind = raw.get(KIND)
    if kind == "THRESHOLD":
        _only(raw, {KIND, COMPARATOR, VALUE})
        return ThresholdRule(
            comparator=_comparator(raw), value_mg_dl=_glucose(raw, VALUE)
        )
    if kind == "DURATION":
        _only(raw, {KIND, COMPARATOR, VALUE, MINUTES})
        return DurationRule(
            comparator=_comparator(raw),
            value_mg_dl=_glucose(raw, VALUE),
            lasting=timedelta(minutes=_minutes(raw, MINUTES)),
        )
    if kind == "RATE_OF_CHANGE":
        _only(raw, {KIND, DIRECTION, RATE, WITHIN})
        return RateOfChangeRule(
            direction=_direction(raw),
            mg_dl_per_min=_rate(raw),
            within=timedelta(minutes=_minutes(raw, WITHIN)),
        )
    raise invalid_rule("unknown_node")


def _group(
    raw: Mapping[str, object], *, depth: int, counter: _NodeCounter
) -> AlertRuleNode:
    _only(raw, {OP, CHILDREN})
    children = raw.get(CHILDREN)
    if not isinstance(children, list) or not children:
        raise invalid_rule("empty_children")
    parsed = [_parse(child, depth=depth + 1, counter=counter) for child in children]
    match raw.get(OP):
        case "ALL_OF":
            return AllOfRule(parsed)
        case "ANY_OF":
            return AnyOfRule(parsed)
        case _:
            raise invalid_rule("unknown_operator")


def _only(raw: Mapping[str, object], allowed: set[str]) -> None:
    if set(raw) - allowed:
        raise invalid_rule("unknown_field")


def _comparator(raw: Mapping[str, object]) -> Comparator:
    try:
        return Comparator(str(raw.get(COMPARATOR)))
    except ValueError:
        raise invalid_rule("invalid_comparator") from None


def _direction(raw: Mapping[str, object]) -> RateDirection:
    try:
        return RateDirection(str(raw.get(DIRECTION)))
    except ValueError:
        raise invalid_rule("invalid_direction") from None


def _number(raw: Mapping[str, object], key: str, *, limit: int) -> Decimal:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise invalid_rule(f"invalid_{key}")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise invalid_rule(f"invalid_{key}") from None
    if not number.is_finite() or not Decimal(0) < number <= Decimal(limit):
        raise invalid_rule(f"invalid_{key}")
    return number


def _glucose(raw: Mapping[str, object], key: str) -> Decimal:
    return _number(raw, key, limit=FieldLimits.GLUCOSE_VALUE_INPUT_MAX)


def _rate(raw: Mapping[str, object]) -> Decimal:
    return _number(raw, RATE, limit=FieldLimits.ALERT_RATE_INPUT_MAX)


def _minutes(raw: Mapping[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_rule(f"invalid_{key}")
    if not FieldLimits.ALERT_MINUTES_MIN <= value <= FieldLimits.ALERT_MINUTES_MAX:
        raise invalid_rule(f"invalid_{key}")
    return value
