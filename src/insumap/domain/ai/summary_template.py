"""The deterministic clinical summary (IA5 fallback, Modulo-IA 6.5).

The template fills its sections with the numbers the backend computed and adds no
narrative, so it cannot invent a claim. It returns keys and parameters only; the
Spanish text is rendered by the caller from ``messages_es``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import final

PERIOD_SECTION: str = "ai.summary.period"
ADHERENCE_SECTION: str = "ai.summary.adherence"


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryNumbers:
    """The figures the template may print. ``None`` means the data does not allow it."""

    tir_pct: Decimal | None
    target_tir_pct: Decimal
    gmi_pct: Decimal | None
    hypo_events_count: int | None
    readings_per_day: Decimal | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class TemplateSection:
    """One section: the message keys of its title and text, and the figures for them."""

    key: str
    params: Mapping[str, object]
    refs: tuple[str, ...]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class SummaryTemplate:
    """The sections of the template, or ``None`` when a key figure is missing."""

    sections: tuple[TemplateSection, ...]


def build_summary_template(numbers: SummaryNumbers) -> SummaryTemplate | None:
    """The sections for the figures, or ``None`` without the key figures."""
    if numbers.tir_pct is None or numbers.gmi_pct is None:
        return None
    if numbers.hypo_events_count is None:
        return None
    sections = [
        TemplateSection(
            key=PERIOD_SECTION,
            params={
                "tir_pct": _fmt(numbers.tir_pct),
                "target_pct": _fmt(numbers.target_tir_pct),
                "gmi_pct": _fmt(numbers.gmi_pct),
                "hypo_events": numbers.hypo_events_count,
            },
            refs=("metric:tir_pct", "metric:gmi_pct", "metric:hypo_events_count"),
        )
    ]
    if numbers.readings_per_day is not None:
        sections.append(
            TemplateSection(
                key=ADHERENCE_SECTION,
                params={"readings_per_day": _fmt(numbers.readings_per_day)},
                refs=("metric:readings_per_day_avg",),
            )
        )
    return SummaryTemplate(sections=tuple(sections))


def _fmt(value: Decimal) -> str:
    """Two decimals with a decimal comma, as the Spanish reader expects."""
    return f"{value:.2f}".replace(".", ",")
