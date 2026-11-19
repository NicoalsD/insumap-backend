"""The deterministic summary (IA5 fallback): its figures and when it does not apply."""

from decimal import Decimal

from insumap.domain.ai.summary_template import (
    ADHERENCE_SECTION,
    PERIOD_SECTION,
    SummaryNumbers,
    build_summary_template,
)


def numbers(**overrides: object) -> SummaryNumbers:
    values: dict[str, object] = {
        "tir_pct": Decimal("48.2"),
        "target_tir_pct": Decimal("70"),
        "gmi_pct": Decimal("7.5"),
        "hypo_events_count": 6,
        "readings_per_day": Decimal("270"),
    }
    values.update(overrides)
    return SummaryNumbers(**values)  # type: ignore[arg-type]


def test_the_template_prints_the_figures_with_a_decimal_comma() -> None:
    template = build_summary_template(numbers())

    assert template is not None
    period, adherence = template.sections
    assert period.key == PERIOD_SECTION
    assert period.params == {
        "tir_pct": "48,20",
        "target_pct": "70,00",
        "gmi_pct": "7,50",
        "hypo_events": 6,
    }
    assert "metric:tir_pct" in period.refs
    assert adherence.key == ADHERENCE_SECTION
    assert adherence.params == {"readings_per_day": "270,00"}


def test_without_readings_the_adherence_section_is_left_out() -> None:
    template = build_summary_template(numbers(readings_per_day=None))

    assert template is not None
    assert [section.key for section in template.sections] == [PERIOD_SECTION]


def test_a_missing_key_figure_gives_no_template() -> None:
    assert build_summary_template(numbers(tir_pct=None)) is None
    assert build_summary_template(numbers(gmi_pct=None)) is None
    assert build_summary_template(numbers(hypo_events_count=None)) is None
