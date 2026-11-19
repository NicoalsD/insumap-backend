"""Value objects of a treatment plan and of a protocol template.

Plain immutable data: no identifiers are generated here and nothing reads the
clock. Clinical parameters (dose ceilings, gaps between doses, titration steps)
are data the clinic configures in a protocol template; they never become a
literal in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from enum import StrEnum
from typing import final
from uuid import UUID

from insumap.domain.monitoring.injection_sites import SiteCode


class ItemType(StrEnum):
    """Kind of a plan item (``care.treatment_plan_items.item_type``)."""

    INSULIN = "INSULIN"
    MEDICATION = "MEDICATION"
    MEASURE = "MEASURE"


class InsulinKind(StrEnum):
    """Class of an insulin item (``care.treatment_plan_items.insulin_kind``)."""

    BASAL = "BASAL"
    BOLUS = "BOLUS"
    CORRECTION = "CORRECTION"
    MIXED = "MIXED"


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemSpec:
    """One item of a plan or of a template, before it has an identifier.

    ``days_of_week`` uses 1 (Monday) to 7 (Sunday); ``None`` means every day.
    ``injection_sites`` are the sites the doctor allows for an insulin item;
    ``None`` means every site.
    """

    item_type: ItemType
    name: str
    insulin_kind: InsulinKind | None = None
    dose_units: Decimal | None = None
    time_of_day: time | None = None
    days_of_week: tuple[int, ...] | None = None
    instructions: str | None = None
    sort_order: int = 0
    injection_sites: tuple[SiteCode, ...] | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class PlanItem(ItemSpec):
    """An item of a stored plan: the same content plus its identifier."""

    item_id: UUID

    @classmethod
    def of(cls, item_id: UUID, spec: ItemSpec) -> PlanItem:
        """The item ``spec`` with the identifier ``item_id``."""
        values = {name: getattr(spec, name) for name in ItemSpec.__dataclass_fields__}
        return cls(item_id=item_id, **values)


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class TitrationRules:
    """How a dose may be adjusted over time, copied from the protocol (DB data)."""

    step_units: Decimal
    max_change_units: Decimal
    min_days_between_adjustments: int


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class ProtocolLimits:
    """Ceilings the protocol sets for a plan; ``None`` means the protocol sets none."""

    max_dose_units: Decimal | None = None
    min_gap_minutes: int | None = None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class TemplateContent:
    """What a protocol template holds: its items, its rules and its limits."""

    items: tuple[ItemSpec, ...]
    titration_rules: TitrationRules | None = None
    limits: ProtocolLimits | None = None
