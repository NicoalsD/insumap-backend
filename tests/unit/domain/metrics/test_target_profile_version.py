"""Invariants and versioning of the target profile versions (no database)."""

from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from uuid import UUID

import pytest

from insumap.domain.metrics.target_profile_version import (
    ACTIVE,
    RETIRED,
    TargetProfileInvariantError,
    TargetProfileValues,
    TargetProfileVersion,
)
from insumap.shared.errors import ErrorCode

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
ACTOR = UUID(int=1)
CLINIC = UUID(int=2)


def values(**overrides: object) -> TargetProfileValues:
    """A consistent set of values; the numbers are fixtures, not clinical rules."""
    base: dict[str, object] = {
        "label": "Perfil de prueba",
        "population": "ADULT",
        "is_default": False,
        "range_low_mg_dl": Decimal("70.0"),
        "range_high_mg_dl": Decimal("180.0"),
        "very_low_mg_dl": Decimal("54.0"),
        "very_high_mg_dl": Decimal("250.0"),
        "tir_min_pct": Decimal("70.00"),
        "tbr_l1_max_pct": Decimal("4.00"),
        "tbr_l2_max_pct": Decimal("1.00"),
        "tar_l1_max_pct": Decimal("25.00"),
        "tar_l2_max_pct": Decimal("5.00"),
        "cv_max_pct": Decimal("36.00"),
        "min_data_sufficiency_pct": Decimal("70.00"),
        "min_days": 14,
        "max_gap_minutes": 15,
        "hypo_episode_min_minutes": 15,
        "min_readings_for_cv": 100,
        "min_readings_for_cv_smbg": 3,
        "night_start": time(0, 0),
        "night_end": time(6, 0),
        "source_reference": "Consenso de prueba, tabla 1",
    }
    base.update(overrides)
    return TargetProfileValues(**base)  # type: ignore[arg-type]


def version(**overrides: object) -> TargetProfileVersion:
    return TargetProfileVersion(
        id=UUID(int=10),
        clinic_id=CLINIC,
        code="CLINIC_TARGETS",
        version=1,
        status=ACTIVE,
        values=values(**overrides),
        created_at=NOW,
        created_by=ACTOR,
        activated_at=NOW,
    )


def test_consistent_values_have_no_violation() -> None:
    assert values().violations() == ()


def test_range_must_be_ordered() -> None:
    found = values(range_high_mg_dl=Decimal("70.0")).violations()

    assert [(v.field, v.type) for v in found] == [
        ("body.range_high_mg_dl", "invalid_order")
    ]


def test_very_low_must_be_below_the_range_and_very_high_above_it() -> None:
    found = values(
        very_low_mg_dl=Decimal("75.0"), very_high_mg_dl=Decimal("170.0")
    ).violations()

    assert {(v.field, v.type) for v in found} == {
        ("body.very_low_mg_dl", "invalid_order"),
        ("body.very_high_mg_dl", "invalid_order"),
    }


@pytest.mark.parametrize("field", ["tir_min_pct", "cv_max_pct"])
def test_percentages_stay_between_zero_and_one_hundred(field: str) -> None:
    above = values(**{field: Decimal("100.01")}).violations()
    below = values(**{field: Decimal("-0.01")}).violations()

    assert [(v.field, v.type) for v in above] == [(f"body.{field}", "out_of_range")]
    assert [(v.field, v.type) for v in below] == [(f"body.{field}", "out_of_range")]


def test_counts_must_be_positive() -> None:
    found = values(min_days=0, min_readings_for_cv=0).violations()

    assert {(v.field, v.type) for v in found} == {
        ("body.min_days", "not_positive"),
        ("body.min_readings_for_cv", "not_positive"),
    }


def test_fasting_high_must_not_be_below_fasting_low_when_both_are_given() -> None:
    crossed = values(
        fasting_low_mg_dl=Decimal("130"), fasting_high_mg_dl=Decimal("80")
    ).violations()
    only_one = values(fasting_low_mg_dl=Decimal("80")).violations()

    assert [(v.field, v.type) for v in crossed] == [
        ("body.fasting_high_mg_dl", "invalid_order")
    ]
    assert only_one == ()


def test_every_broken_rule_is_listed_in_the_error() -> None:
    with pytest.raises(TargetProfileInvariantError) as raised:
        values(range_high_mg_dl=Decimal("60.0"), min_days=0).ensure_valid()

    assert raised.value.code is ErrorCode.VALIDATION_ERROR
    errors = raised.value.detail["errors"]
    assert errors == [
        {"field": "body.range_high_mg_dl", "type": "invalid_order"},
        {"field": "body.min_days", "type": "not_positive"},
    ]


def test_copy_for_new_version_applies_changes_and_increments_the_number() -> None:
    current = version()
    new_id = UUID(int=11)

    copy = current.copy_for_new_version(
        new_id=new_id,
        changes={"tir_min_pct": Decimal("75.00")},
        by=ACTOR,
        change_reason="Ajuste por decisión del comité",
        at=NOW,
    )

    assert copy.id == new_id
    assert copy.version == 2
    assert copy.status == ACTIVE
    assert copy.values.tir_min_pct == Decimal("75.00")
    assert copy.values.range_high_mg_dl == current.values.range_high_mg_dl
    assert copy.change_reason == "Ajuste por decisión del comité"
    assert copy.clinic_id == CLINIC
    assert current.values.tir_min_pct == Decimal("70.00")


def test_copy_validates_the_whole_profile_not_only_the_change() -> None:
    current = version()

    with pytest.raises(TargetProfileInvariantError):
        current.copy_for_new_version(
            new_id=UUID(int=11),
            changes={"range_high_mg_dl": Decimal("60.0")},
            by=ACTOR,
            change_reason="Cambio que rompe el orden",
            at=NOW,
        )


def test_retired_version_keeps_its_values() -> None:
    retired = version().retired()

    assert retired.status == RETIRED
    assert retired.values == version().values


def test_metrics_profile_projects_the_metric_fields() -> None:
    profile = replace(version(), version=3).metrics_profile()

    assert profile.id == UUID(int=10)
    assert profile.version == 3
    assert profile.range_low_mg_dl == Decimal("70.0")
    assert profile.min_readings_for_cv_smbg == 3
    assert profile.night_end == time(6, 0)
