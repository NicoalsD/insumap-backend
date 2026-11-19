"""Primitive (JSON-ready) form of the treatment content.

The memento (P16) and the jsonb columns of ``care.protocol_templates`` and
``care.treatment_plan_snapshots`` store only strings, numbers, booleans, lists,
objects and ``None``. These functions are the only place where the conversion
happens, in both directions, so a round trip returns equal values.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
from decimal import Decimal
from typing import Any, Final, cast
from uuid import UUID

from insumap.domain.treatment.content import (
    InsulinKind,
    ItemSpec,
    ItemType,
    PlanItem,
    ProtocolLimits,
    TemplateContent,
    TitrationRules,
)

type Primitive = dict[str, Any]

ITEMS_KEY: Final = "items"
RULES_KEY: Final = "titration_rules"
LIMITS_KEY: Final = "limits"


def decimal_text(value: Decimal | None) -> str | None:
    """A decimal as text, so no float ever rounds it."""
    return None if value is None else str(value)


def item_to_primitive(item: ItemSpec) -> Primitive:
    """An item without identifier, as primitives."""
    return {
        "item_type": item.item_type.value,
        "name": item.name,
        "insulin_kind": None if item.insulin_kind is None else item.insulin_kind.value,
        "dose_units": decimal_text(item.dose_units),
        "time_of_day": None
        if item.time_of_day is None
        else item.time_of_day.isoformat(),
        "days_of_week": None if item.days_of_week is None else list(item.days_of_week),
        "instructions": item.instructions,
        "sort_order": item.sort_order,
    }


def item_spec_from_primitive(data: Mapping[str, Any]) -> ItemSpec:
    """The item described by ``data``; the inverse of ``item_to_primitive``."""
    insulin = data["insulin_kind"]
    dose = data["dose_units"]
    at = data["time_of_day"]
    days = data["days_of_week"]
    return ItemSpec(
        item_type=ItemType(data["item_type"]),
        name=str(data["name"]),
        insulin_kind=None if insulin is None else InsulinKind(insulin),
        dose_units=None if dose is None else Decimal(str(dose)),
        time_of_day=None if at is None else time.fromisoformat(str(at)),
        days_of_week=None if days is None else tuple(int(day) for day in days),
        instructions=cast("str | None", data["instructions"]),
        sort_order=int(data["sort_order"]),
    )


def plan_item_to_primitive(item: PlanItem) -> Primitive:
    """A stored item, identifier included."""
    return {"item_id": str(item.item_id), **item_to_primitive(item)}


def plan_item_from_primitive(data: Mapping[str, Any]) -> PlanItem:
    """A stored item rebuilt from its primitives."""
    return PlanItem.of(UUID(str(data["item_id"])), item_spec_from_primitive(data))


def rules_to_primitive(rules: TitrationRules | None) -> Primitive | None:
    """The titration rules, or ``None`` when the protocol sets none."""
    if rules is None:
        return None
    return {
        "step_units": decimal_text(rules.step_units),
        "max_change_units": decimal_text(rules.max_change_units),
        "min_days_between_adjustments": rules.min_days_between_adjustments,
    }


def rules_from_primitive(data: Mapping[str, Any] | None) -> TitrationRules | None:
    """The titration rules from their primitives."""
    if data is None:
        return None
    return TitrationRules(
        step_units=Decimal(str(data["step_units"])),
        max_change_units=Decimal(str(data["max_change_units"])),
        min_days_between_adjustments=int(data["min_days_between_adjustments"]),
    )


def limits_to_primitive(limits: ProtocolLimits | None) -> Primitive | None:
    """The protocol limits, or ``None``."""
    if limits is None:
        return None
    return {
        "max_dose_units": decimal_text(limits.max_dose_units),
        "min_gap_minutes": limits.min_gap_minutes,
    }


def limits_from_primitive(data: Mapping[str, Any] | None) -> ProtocolLimits | None:
    """The protocol limits from their primitives."""
    if data is None:
        return None
    dose = data["max_dose_units"]
    gap = data["min_gap_minutes"]
    return ProtocolLimits(
        max_dose_units=None if dose is None else Decimal(str(dose)),
        min_gap_minutes=None if gap is None else int(gap),
    )


def template_content_to_primitive(content: TemplateContent) -> Primitive:
    """The jsonb object of a protocol template: items, rules and limits."""
    document: Primitive = {
        ITEMS_KEY: [item_to_primitive(item) for item in content.items]
    }
    if content.titration_rules is not None:
        document[RULES_KEY] = rules_to_primitive(content.titration_rules)
    if content.limits is not None:
        document[LIMITS_KEY] = limits_to_primitive(content.limits)
    return document


def template_content_from_primitive(data: Mapping[str, Any]) -> TemplateContent:
    """The template content from its jsonb object."""
    items = cast("list[Mapping[str, Any]]", data[ITEMS_KEY])
    return TemplateContent(
        items=tuple(item_spec_from_primitive(item) for item in items),
        titration_rules=rules_from_primitive(data.get(RULES_KEY)),
        limits=limits_from_primitive(data.get(LIMITS_KEY)),
    )
