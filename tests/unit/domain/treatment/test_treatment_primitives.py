"""The jsonb form of the treatment content round-trips without losing a value."""

from dataclasses import replace
from datetime import time
from decimal import Decimal

from insumap.domain.monitoring.injection_sites import SiteCode
from insumap.domain.treatment.content import (
    InsulinKind,
    ItemSpec,
    ItemType,
    ProtocolLimits,
    TemplateContent,
    TitrationRules,
)
from insumap.domain.treatment.primitives import (
    item_spec_from_primitive,
    item_to_primitive,
    limits_from_primitive,
    limits_to_primitive,
    rules_from_primitive,
    rules_to_primitive,
    template_content_from_primitive,
    template_content_to_primitive,
)
from tests.unit.domain.treatment.factories import insulin, measure


def test_full_template_content_round_trips_through_primitives() -> None:
    content = TemplateContent(
        items=(insulin("Basal", days=(1, 3)), measure("06:30")),
        titration_rules=TitrationRules(
            step_units=Decimal("0.5"),
            max_change_units=Decimal("2"),
            min_days_between_adjustments=3,
        ),
        limits=ProtocolLimits(max_dose_units=Decimal("20"), min_gap_minutes=60),
    )

    restored = template_content_from_primitive(template_content_to_primitive(content))

    assert restored == content


def test_missing_rules_and_limits_stay_missing() -> None:
    content = TemplateContent(items=(measure(),))

    document = template_content_to_primitive(content)
    restored = template_content_from_primitive(document)

    assert "titration_rules" not in document
    assert "limits" not in document
    assert restored == content


def test_partial_limits_keep_the_unset_fields_as_none() -> None:
    limits = ProtocolLimits(max_dose_units=None, min_gap_minutes=15)

    assert limits_from_primitive(limits_to_primitive(limits)) == limits
    assert limits_to_primitive(None) is None
    assert limits_from_primitive(None) is None


def test_rules_and_none_convert_both_ways() -> None:
    rules = TitrationRules(
        step_units=Decimal("1"),
        max_change_units=Decimal("4"),
        min_days_between_adjustments=0,
    )

    assert rules_from_primitive(rules_to_primitive(rules)) == rules
    assert rules_to_primitive(None) is None
    assert rules_from_primitive(None) is None


def test_an_item_keeps_its_insulin_kind_and_time() -> None:
    spec = ItemSpec(
        item_type=ItemType.INSULIN,
        name="Correctiva",
        insulin_kind=InsulinKind.CORRECTION,
        dose_units=Decimal("2.25"),
        time_of_day=time(12, 15),
        days_of_week=None,
        instructions="Antes del almuerzo",
    )

    restored = template_content_from_primitive(
        template_content_to_primitive(TemplateContent(items=(spec,)))
    )

    assert restored.items == (spec,)


def test_the_injection_sites_of_an_item_round_trip() -> None:
    spec = replace(
        insulin("Basal"),
        injection_sites=(SiteCode.ABDOMEN_LEFT, SiteCode.THIGH_RIGHT),
    )

    restored = item_spec_from_primitive(item_to_primitive(spec))

    assert restored.injection_sites == (SiteCode.ABDOMEN_LEFT, SiteCode.THIGH_RIGHT)
    assert item_to_primitive(spec)["injection_sites"] == [
        "ABDOMEN_LEFT",
        "THIGH_RIGHT",
    ]
    assert (
        item_spec_from_primitive(item_to_primitive(insulin())).injection_sites is None
    )


def test_a_snapshot_saved_before_the_injection_sites_still_reads() -> None:
    legacy = item_to_primitive(insulin("Basal"))
    del legacy["injection_sites"]

    assert item_spec_from_primitive(legacy).injection_sites is None
    content = template_content_from_primitive({"items": [legacy]})
    assert content.items[0].injection_sites is None
