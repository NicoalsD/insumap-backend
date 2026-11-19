"""Content a caller sends for a plan: the items, the titration rules and the notes."""

from __future__ import annotations

from dataclasses import dataclass

from insumap.domain.treatment.content import ItemSpec, TitrationRules


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanContentInput:
    """What a plan holds, before the plan gives its items their identifiers."""

    items: tuple[ItemSpec, ...]
    titration_rules: TitrationRules | None = None
    notes: str | None = None
