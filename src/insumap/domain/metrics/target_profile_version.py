"""Versions of a target profile: the catalog rows behind ``TargetProfile``.

The clinical values are data of ``care.target_profiles`` (API.md 8.7, metrics
doc section 7.5): nothing in this module is a clinical number. The invariants
are the ones the database checks (ranges ordered, percentages between 0 and
100, counts positive, fasting high not below fasting low), so a value the
database would refuse is refused here first, with its field and kind.

A version never changes after it is active: a change copies the active version,
applies the changes, validates the whole result and gives the copy the next
number (``copy_for_new_version``). Metrics already computed keep the version
they used.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time
from decimal import Decimal
from typing import Any, Final, final
from uuid import UUID

from insumap.domain.metrics.target_profile import TargetProfile
from insumap.shared.errors import ErrorCode, InsumapError

ACTIVE: Final = "ACTIVE"
RETIRED: Final = "RETIRED"

PERCENT_MIN: Final = Decimal(0)
PERCENT_MAX: Final = Decimal(100)
"""Bounds of every ``*_pct`` value (a percentage of the time or of the data)."""

PERCENT_FIELDS: Final = (
    "tir_min_pct",
    "tbr_l1_max_pct",
    "tbr_l2_max_pct",
    "tar_l1_max_pct",
    "tar_l2_max_pct",
    "cv_max_pct",
    "min_data_sufficiency_pct",
)
COUNT_FIELDS: Final = (
    "min_days",
    "max_gap_minutes",
    "hypo_episode_min_minutes",
    "min_readings_for_cv",
    "min_readings_for_cv_smbg",
)
OPTIONAL_POSITIVE_FIELDS: Final = (
    "hba1c_goal_pct",
    "fasting_low_mg_dl",
    "postprandial_max_mg_dl",
    "postprandial_1h_max_mg_dl",
    "postprandial_2h_max_mg_dl",
)

POSITIVE: Final = "not_positive"
ORDER: Final = "invalid_order"
OUT_OF_RANGE: Final = "out_of_range"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileViolation:
    """One broken rule: the field of the request and the kind of rule."""

    field: str
    type: str

    def as_detail(self) -> dict[str, str]:
        return {"field": self.field, "type": self.type}


@final
class TargetProfileInvariantError(InsumapError):
    """The values break a rule of the goals; every broken rule is listed (422)."""

    def __init__(self, violations: tuple[ProfileViolation, ...]) -> None:
        super().__init__(
            ErrorCode.VALIDATION_ERROR,
            detail={"errors": [v.as_detail() for v in violations]},
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetProfileValues:
    """Every editable value of a profile version (no identity, no status)."""

    label: str
    population: str
    is_default: bool
    range_low_mg_dl: Decimal
    range_high_mg_dl: Decimal
    very_low_mg_dl: Decimal
    very_high_mg_dl: Decimal
    tir_min_pct: Decimal
    tbr_l1_max_pct: Decimal
    tbr_l2_max_pct: Decimal
    tar_l1_max_pct: Decimal
    tar_l2_max_pct: Decimal
    cv_max_pct: Decimal
    min_data_sufficiency_pct: Decimal
    min_days: int
    max_gap_minutes: int
    hypo_episode_min_minutes: int
    min_readings_for_cv: int
    min_readings_for_cv_smbg: int
    night_start: time
    night_end: time
    source_reference: str
    hba1c_goal_pct: Decimal | None = None
    fasting_low_mg_dl: Decimal | None = None
    fasting_high_mg_dl: Decimal | None = None
    postprandial_max_mg_dl: Decimal | None = None
    postprandial_1h_max_mg_dl: Decimal | None = None
    postprandial_2h_max_mg_dl: Decimal | None = None

    def violations(self) -> tuple[ProfileViolation, ...]:
        """Every rule the values break, in the order of the fields."""
        found: list[ProfileViolation] = []

        def check(ok: bool, field: str, kind: str) -> None:
            if not ok:
                found.append(ProfileViolation(field=f"body.{field}", type=kind))

        check(self.range_low_mg_dl > 0, "range_low_mg_dl", POSITIVE)
        check(self.range_high_mg_dl > self.range_low_mg_dl, "range_high_mg_dl", ORDER)
        check(self.very_low_mg_dl > 0, "very_low_mg_dl", POSITIVE)
        check(self.very_low_mg_dl < self.range_low_mg_dl, "very_low_mg_dl", ORDER)
        check(self.very_high_mg_dl > self.range_high_mg_dl, "very_high_mg_dl", ORDER)
        for name in PERCENT_FIELDS:
            value: Decimal = getattr(self, name)
            check(PERCENT_MIN <= value <= PERCENT_MAX, name, OUT_OF_RANGE)
        for name in COUNT_FIELDS:
            count: int = getattr(self, name)
            check(count > 0, name, POSITIVE)
        for name in OPTIONAL_POSITIVE_FIELDS:
            optional: Decimal | None = getattr(self, name)
            if optional is not None:
                check(optional > 0, name, POSITIVE)
        if self.fasting_low_mg_dl is not None and self.fasting_high_mg_dl is not None:
            check(
                self.fasting_high_mg_dl >= self.fasting_low_mg_dl,
                "fasting_high_mg_dl",
                ORDER,
            )
        return tuple(found)

    def ensure_valid(self) -> None:
        """Raise ``TargetProfileInvariantError`` listing every broken rule."""
        violations = self.violations()
        if violations:
            raise TargetProfileInvariantError(violations)


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetProfileVersion:
    """One version of a profile of a clinic, or a global seed (``clinic_id`` None).

    Pattern: P05 Prototype (``copy_for_new_version`` clones the active version)
    """

    id: UUID
    clinic_id: UUID | None
    code: str
    version: int
    status: str
    values: TargetProfileValues
    created_at: datetime
    created_by: UUID | None = None
    change_reason: str | None = None
    activated_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == ACTIVE

    def metrics_profile(self) -> TargetProfile:
        """The part of this version the metrics read (``TargetProfile``)."""
        v = self.values
        return TargetProfile(
            id=self.id,
            code=self.code,
            version=self.version,
            population=v.population,
            range_low_mg_dl=v.range_low_mg_dl,
            range_high_mg_dl=v.range_high_mg_dl,
            very_low_mg_dl=v.very_low_mg_dl,
            very_high_mg_dl=v.very_high_mg_dl,
            tir_min_pct=v.tir_min_pct,
            tbr_l1_max_pct=v.tbr_l1_max_pct,
            tbr_l2_max_pct=v.tbr_l2_max_pct,
            tar_l1_max_pct=v.tar_l1_max_pct,
            tar_l2_max_pct=v.tar_l2_max_pct,
            cv_max_pct=v.cv_max_pct,
            min_data_sufficiency_pct=v.min_data_sufficiency_pct,
            min_days=v.min_days,
            max_gap_minutes=v.max_gap_minutes,
            hypo_episode_min_minutes=v.hypo_episode_min_minutes,
            min_readings_for_cv=v.min_readings_for_cv,
            min_readings_for_cv_smbg=v.min_readings_for_cv_smbg,
            night_start=v.night_start,
            night_end=v.night_end,
        )

    def copy_for_new_version(
        self,
        *,
        new_id: UUID,
        changes: Mapping[str, Any],
        by: UUID,
        change_reason: str,
        at: datetime,
    ) -> TargetProfileVersion:
        """The next version: this one with ``changes`` applied, active from ``at``.

        The result is validated as a whole, so a change that is valid alone but
        breaks an ordering with another value is refused.
        """
        values = replace(self.values, **changes)
        values.ensure_valid()
        return TargetProfileVersion(
            id=new_id,
            clinic_id=self.clinic_id,
            code=self.code,
            version=self.version + 1,
            status=ACTIVE,
            values=values,
            created_at=at,
            created_by=by,
            change_reason=change_reason,
            activated_at=at,
        )

    def retired(self) -> TargetProfileVersion:
        """This version out of use; the only change an active version admits."""
        return replace(self, status=RETIRED)


@dataclass(frozen=True, slots=True, kw_only=True)
class PatientTargetAssignment:
    """The profile of metas assigned to a patient; one open per patient."""

    id: UUID
    clinic_id: UUID
    patient_id: UUID
    target_profile_id: UUID
    assigned_by: UUID
    assigned_at: datetime
    ended_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.ended_at is None

    def ended(self, at: datetime) -> PatientTargetAssignment:
        return replace(self, ended_at=at)
