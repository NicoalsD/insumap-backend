"""Rules of the injection site (port of the frontend mock rules, same cases)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import product
from typing import ClassVar

import pytest

from insumap.domain.monitoring.injection_rule import (
    RULES_VERSION,
    InjectionHistoryEntry,
    InjectionPatientProfile,
    InjectionRuleInput,
    InjectionRulesV1Strategy,
    InjectionSites,
    InjectionSiteStatus,
    LipohypertrophyReport,
    age_in_years,
    is_lean,
    plan_sites_for,
)
from insumap.domain.monitoring.injection_sites import (
    SITE_ORDER,
    NeedleNote,
    PregnancyStatus,
    ReasonCode,
    SiteCode,
    SiteState,
)
from insumap.domain.monitoring.records import InsulinKind
from insumap.domain.onboarding.vocabulary import Sex

NOW = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
NINETY_DAYS = timedelta(days=90)

BASAL = InsulinKind.BASAL
BOLUS = InsulinKind.BOLUS
CORRECTION = InsulinKind.CORRECTION
MIXED = InsulinKind.MIXED

ABDOMEN_RIGHT = SiteCode.ABDOMEN_RIGHT
ABDOMEN_LEFT = SiteCode.ABDOMEN_LEFT
THIGH_RIGHT = SiteCode.THIGH_RIGHT
THIGH_LEFT = SiteCode.THIGH_LEFT
ARM_RIGHT = SiteCode.ARM_RIGHT
ARM_LEFT = SiteCode.ARM_LEFT
BUTTOCK_RIGHT = SiteCode.BUTTOCK_RIGHT
BUTTOCK_LEFT = SiteCode.BUTTOCK_LEFT

LIMBS = (ARM_LEFT, ARM_RIGHT, THIGH_LEFT, THIGH_RIGHT)
STRATEGY = InjectionRulesV1Strategy()


def hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def days_ago(days: float) -> datetime:
    return hours_ago(days * 24)


WOMAN = InjectionPatientProfile(
    sex=Sex.FEMALE,
    birth_date=date(1992, 3, 18),
    bmi=Decimal("23.4"),
    pregnancy=PregnancyStatus.NONE,
)
MAN = InjectionPatientProfile(
    sex=Sex.MALE,
    birth_date=date(1992, 3, 18),
    bmi=Decimal(26),
    pregnancy=PregnancyStatus.NONE,
)


def profile(
    *,
    sex: Sex = Sex.FEMALE,
    birth_date: date | None = date(1992, 3, 18),
    bmi: Decimal | None = Decimal("23.4"),
    pregnancy: PregnancyStatus = PregnancyStatus.NONE,
    lipohypertrophy: tuple[LipohypertrophyReport, ...] = (),
) -> InjectionPatientProfile:
    return InjectionPatientProfile(
        sex=sex,
        birth_date=birth_date,
        bmi=bmi,
        pregnancy=pregnancy,
        lipohypertrophy=lipohypertrophy,
    )


def lipo(site: SiteCode, days: float) -> LipohypertrophyReport:
    return LipohypertrophyReport(site=site, reported_at=days_ago(days))


def dose(
    site: SiteCode, spot: int, hours: float, kind: InsulinKind = BOLUS
) -> InjectionHistoryEntry:
    return InjectionHistoryEntry(
        site=site, spot=spot, kind=kind, administered_at=hours_ago(hours)
    )


def run(
    *,
    kind: InsulinKind = BOLUS,
    who: InjectionPatientProfile = WOMAN,
    plan: tuple[SiteCode, ...] | None = None,
    history: tuple[InjectionHistoryEntry, ...] = (),
) -> InjectionSites:
    return STRATEGY.suggest(
        InjectionRuleInput(kind=kind, now=NOW, profile=who, plan=plan, history=history)
    )


def status_of(result: InjectionSites, site: SiteCode) -> InjectionSiteStatus:
    return next(row for row in result.sites if row.site is site)


def suggested_site(result: InjectionSites) -> SiteCode:
    assert result.suggestion is not None
    return result.suggestion.site


def test_age_in_years_counts_whole_years_and_flips_on_the_birthday_in_utc() -> None:
    assert age_in_years(date(2008, 11, 19), NOW) == 18
    assert age_in_years(date(2008, 11, 20), NOW) == 17
    assert age_in_years(date(1992, 3, 18), NOW) == 34


def test_is_lean_uses_bmi_under_20_for_everyone_and_under_22_for_men() -> None:
    assert is_lean(Sex.FEMALE, Decimal("19.9"))
    assert not is_lean(Sex.FEMALE, Decimal(20))
    assert is_lean(Sex.MALE, Decimal("21.9"))
    assert not is_lean(Sex.MALE, Decimal(22))
    assert not is_lean(Sex.UNKNOWN, Decimal(21))


@pytest.mark.parametrize("sex", list(Sex))
def test_is_lean_is_never_true_without_a_bmi(sex: Sex) -> None:
    assert not is_lean(sex, None)


class TestPlanSitesFor:
    def test_is_none_when_no_item_restricts_the_sites(self) -> None:
        assert plan_sites_for([None, None]) is None
        assert plan_sites_for([]) is None

    def test_returns_the_restricted_sites_in_canonical_order(self) -> None:
        assert plan_sites_for([None, (THIGH_RIGHT, ABDOMEN_LEFT)]) == (
            ABDOMEN_LEFT,
            THIGH_RIGHT,
        )

    def test_intersects_several_restrictions_of_the_same_kind(self) -> None:
        first = (ABDOMEN_LEFT, THIGH_RIGHT, ARM_LEFT)
        second = (THIGH_RIGHT, ARM_LEFT)
        assert plan_sites_for([first, second]) == (THIGH_RIGHT, ARM_LEFT)


class TestBolusAndCorrectionAbdomenFirst:
    def test_suggests_the_abdomen_with_spot_1_for_a_woman_with_no_history(
        self,
    ) -> None:
        result = run()
        suggestion = result.suggestion
        assert suggestion is not None
        assert suggestion.site is ABDOMEN_RIGHT
        assert suggestion.spot == 1
        assert suggestion.reason_codes == (ReasonCode.FASTEST_ABSORPTION,)
        assert suggestion.needle_note is NeedleNote.PINCH_OPTIONAL
        assert not suggestion.pinch_up
        assert result.kind is BOLUS
        assert result.rules_version == "injection-rules-1" == RULES_VERSION

    def test_treats_a_correction_like_a_bolus(self) -> None:
        result = run(kind=CORRECTION)
        assert suggested_site(result) is ABDOMEN_RIGHT
        assert result.suggestion is not None
        assert ReasonCode.FASTEST_ABSORPTION in result.suggestion.reason_codes

    def test_keeps_the_mixed_insulin_on_the_abdomen_without_the_bolus_reason(
        self,
    ) -> None:
        result = run(kind=MIXED)
        assert suggested_site(result) is ABDOMEN_RIGHT
        assert result.suggestion is not None
        assert ReasonCode.FASTEST_ABSORPTION not in result.suggestion.reason_codes

    def test_is_the_opposite_of_basal_for_the_same_profile_and_history(self) -> None:
        assert suggested_site(run(kind=BOLUS)).value.startswith("ABDOMEN_")
        assert suggested_site(run(kind=BASAL)).value.startswith("THIGH_")


class TestBasalThighThenButtock:
    def test_suggests_the_thigh_for_a_woman_with_steady_absorption(self) -> None:
        result = run(kind=BASAL)
        assert suggested_site(result) is THIGH_RIGHT
        assert result.suggestion is not None
        assert ReasonCode.STEADY_ABSORPTION in result.suggestion.reason_codes
        assert ReasonCode.FASTEST_ABSORPTION not in result.suggestion.reason_codes

    def test_suggests_the_abdomen_first_for_a_man_then_the_buttock(self) -> None:
        result = run(kind=BASAL, who=MAN)
        assert suggested_site(result) is ABDOMEN_RIGHT
        assert result.suggestion is not None
        assert ReasonCode.STEADY_ABSORPTION not in result.suggestion.reason_codes

        # The right abdomen is the last site used, so the left one comes next.
        with_abdomen_used = run(
            kind=BASAL,
            who=MAN,
            history=(
                dose(ABDOMEN_RIGHT, 1, 30, BASAL),
                dose(ABDOMEN_LEFT, 1, 50, BASAL),
            ),
        )
        assert with_abdomen_used.suggestion is not None
        assert with_abdomen_used.suggestion.site is ABDOMEN_LEFT
        assert with_abdomen_used.suggestion.spot == 2
        assert status_of(with_abdomen_used, ABDOMEN_LEFT).state is SiteState.SUGGESTED

    def test_moves_a_woman_from_a_recent_thigh_to_the_other_thigh(self) -> None:
        result = run(kind=BASAL, history=(dose(THIGH_RIGHT, 1, 10, BASAL),))
        assert suggested_site(result) is THIGH_LEFT

    def test_keeps_the_thighs_while_they_are_eligible(self) -> None:
        # The left thigh (30 h ago) is recent but eligible: it beats the buttock.
        result = run(
            kind=BASAL,
            history=(dose(THIGH_RIGHT, 1, 10, BASAL), dose(THIGH_LEFT, 1, 30, BASAL)),
        )
        assert result.suggestion is not None
        assert result.suggestion.site is THIGH_LEFT
        assert result.suggestion.spot == 2
        assert ReasonCode.STEADY_ABSORPTION in result.suggestion.reason_codes

    def test_moves_to_the_buttock_only_when_both_thighs_are_out(self) -> None:
        result = run(
            kind=BASAL,
            plan=(THIGH_RIGHT, THIGH_LEFT, BUTTOCK_LEFT),
            who=profile(lipohypertrophy=(lipo(THIGH_LEFT, 5),)),
            history=(dose(THIGH_RIGHT, 1, 10, BASAL),),
        )
        assert suggested_site(result) is BUTTOCK_LEFT


class TestPregnancy:
    pregnant = profile(pregnancy=PregnancyStatus.PREGNANT)

    def test_suggests_the_abdomen_with_spot_3_and_the_pregnancy_reason(self) -> None:
        result = run(who=self.pregnant)
        assert result.suggestion is not None
        assert result.suggestion.site is ABDOMEN_RIGHT
        assert result.suggestion.spot == 3
        assert set(result.suggestion.reason_codes) >= {
            ReasonCode.FASTEST_ABSORPTION,
            ReasonCode.PREGNANCY_AVOID_ABDOMEN_CENTER,
        }

    def test_marks_the_other_abdomen_as_allowed_with_the_pregnancy_reason(self) -> None:
        assert status_of(run(who=self.pregnant), ABDOMEN_LEFT) == InjectionSiteStatus(
            site=ABDOMEN_LEFT,
            state=SiteState.ALLOWED,
            reason_code=ReasonCode.PREGNANCY_AVOID_ABDOMEN_CENTER,
            last_used_at=None,
            last_spot=None,
        )

    def test_advances_the_spot_from_3_to_4_on_the_side_not_used_last(self) -> None:
        result = run(
            who=self.pregnant,
            history=(dose(ABDOMEN_LEFT, 3, 50), dose(ABDOMEN_RIGHT, 1, 30)),
        )
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_LEFT, 4)

    def test_returns_from_spot_4_to_3_on_the_side_not_used_last(self) -> None:
        result = run(
            who=self.pregnant,
            history=(dose(ABDOMEN_LEFT, 4, 50), dose(ABDOMEN_RIGHT, 1, 30)),
        )
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_LEFT, 3)

    def test_wraps_from_spot_4_to_3_on_the_other_side(self) -> None:
        result = run(
            who=self.pregnant,
            history=(dose(ABDOMEN_LEFT, 3, 30), dose(ABDOMEN_RIGHT, 4, 50)),
        )
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_RIGHT, 3)

    def test_starts_at_spot_3_when_the_last_spot_was_1_or_2_before(self) -> None:
        result = run(
            who=self.pregnant,
            history=(dose(ABDOMEN_LEFT, 2, 30), dose(ABDOMEN_RIGHT, 1, 60)),
        )
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_RIGHT, 3)

    def test_never_suggests_spots_1_or_2_on_the_abdomen(self) -> None:
        scenarios = (
            (),
            (dose(ABDOMEN_RIGHT, 1, 40),),
            (dose(ABDOMEN_LEFT, 2, 40), dose(ABDOMEN_RIGHT, 4, 60)),
        )
        for history in scenarios:
            result = run(who=self.pregnant, history=history)
            assert result.suggestion is not None
            if result.suggestion.site.value.startswith("ABDOMEN_"):
                assert result.suggestion.spot in {3, 4}

    def test_suggests_the_thigh_for_basal_without_the_pregnancy_reason(self) -> None:
        result = run(kind=BASAL, who=self.pregnant)
        assert suggested_site(result) is THIGH_RIGHT
        assert (
            status_of(result, THIGH_RIGHT).reason_code is ReasonCode.STEADY_ABSORPTION
        )


class TestLeanPatients:
    lean_woman = profile(bmi=Decimal(19))
    lean_man = profile(sex=Sex.MALE, bmi=Decimal(21))

    def test_removes_arms_and_thighs_from_a_bolus_for_a_lean_woman(self) -> None:
        result = run(who=self.lean_woman)
        for site in LIMBS:
            row = status_of(result, site)
            assert row.state is SiteState.AVOID
            assert row.reason_code is ReasonCode.LEAN_AVOID_LIMBS
        assert status_of(result, BUTTOCK_LEFT).state is not SiteState.AVOID

    def test_removes_arms_and_thighs_from_a_bolus_for_a_man_under_bmi_22(self) -> None:
        result = run(who=self.lean_man)
        assert suggested_site(result) is ABDOMEN_RIGHT
        for site in LIMBS:
            assert status_of(result, site).state is SiteState.AVOID
        assert status_of(result, BUTTOCK_RIGHT).state is SiteState.ALLOWED

    def test_does_not_remove_the_limbs_for_a_man_with_bmi_22(self) -> None:
        result = run(who=profile(sex=Sex.MALE, bmi=Decimal(22)))
        for site in LIMBS:
            assert status_of(result, site).state is SiteState.ALLOWED

    def test_keeps_the_limbs_for_a_basal_with_the_pinch_of_the_needle(self) -> None:
        result = run(kind=BASAL, who=self.lean_woman)
        assert suggested_site(result) is THIGH_RIGHT
        assert result.suggestion is not None
        assert result.suggestion.pinch_up
        assert result.suggestion.needle_note is NeedleNote.PINCH_UP
        assert status_of(result, THIGH_RIGHT).state is SiteState.SUGGESTED

    def test_keeps_the_limbs_for_a_mixed_insulin(self) -> None:
        result = run(kind=MIXED, who=self.lean_man)
        assert status_of(result, THIGH_LEFT).state is SiteState.ALLOWED

    def test_keeps_an_arm_the_plan_asks_for_even_for_a_lean_bolus(self) -> None:
        result = run(who=self.lean_man, plan=(ARM_LEFT, ABDOMEN_RIGHT))
        assert status_of(result, ARM_LEFT).state is SiteState.ALLOWED
        assert suggested_site(result) is ABDOMEN_RIGHT

    def test_does_not_treat_an_unknown_bmi_as_lean(self) -> None:
        result = run(who=profile(bmi=None))
        for site in LIMBS:
            assert status_of(result, site).state is SiteState.ALLOWED


class TestPlanRestriction:
    def test_only_suggests_sites_the_plan_allows(self) -> None:
        plan = (ABDOMEN_LEFT, THIGH_RIGHT)
        result = run(kind=BASAL, plan=plan)
        assert suggested_site(result) is THIGH_RIGHT
        for row in result.sites:
            if row.site not in plan:
                assert row.state is SiteState.AVOID
                assert row.reason_code is ReasonCode.PLAN_RESTRICTED

    def test_applies_a_bolus_restriction_to_the_abdomen_only(self) -> None:
        result = run(plan=(ABDOMEN_LEFT,))
        assert suggested_site(result) is ABDOMEN_LEFT
        assert (
            status_of(result, ABDOMEN_RIGHT).reason_code is ReasonCode.PLAN_RESTRICTED
        )

    def test_an_empty_plan_avoids_every_site(self) -> None:
        result = run(plan=())
        assert result.suggestion is None
        assert {row.reason_code for row in result.sites} == {ReasonCode.PLAN_RESTRICTED}


class TestLipohypertrophy:
    def test_avoids_a_site_at_89_days_and_allows_it_after_91(self) -> None:
        recent = run(who=profile(lipohypertrophy=(lipo(ABDOMEN_RIGHT, 89),)))
        row = status_of(recent, ABDOMEN_RIGHT)
        assert row.state is SiteState.AVOID
        assert row.reason_code is ReasonCode.LIPOHYPERTROPHY_REPORTED
        assert suggested_site(recent) is ABDOMEN_LEFT

        old = run(who=profile(lipohypertrophy=(lipo(ABDOMEN_RIGHT, 91),)))
        assert status_of(old, ABDOMEN_RIGHT).state is not SiteState.AVOID
        assert suggested_site(old) is ABDOMEN_RIGHT

    def test_the_90_day_line_is_inclusive(self) -> None:
        exact = LipohypertrophyReport(site=ABDOMEN_RIGHT, reported_at=NOW - NINETY_DAYS)
        result = run(who=profile(lipohypertrophy=(exact,)))
        assert status_of(result, ABDOMEN_RIGHT).state is SiteState.AVOID

    def test_keeps_the_plan_reason_first_when_both_apply(self) -> None:
        result = run(
            plan=(ABDOMEN_LEFT,),
            who=profile(lipohypertrophy=(lipo(ABDOMEN_RIGHT, 10),)),
        )
        assert (
            status_of(result, ABDOMEN_RIGHT).reason_code is ReasonCode.PLAN_RESTRICTED
        )


class TestRotation:
    def test_alternates_to_the_other_side_after_a_dose_on_one_side(self) -> None:
        result = run(history=(dose(ABDOMEN_RIGHT, 1, 30),))
        suggestion = result.suggestion
        assert suggestion is not None
        assert suggestion.site is ABDOMEN_LEFT
        assert suggestion.spot == 1
        assert suggestion.reason_codes == (ReasonCode.FASTEST_ABSORPTION,)
        assert suggestion.needle_note is NeedleNote.PINCH_OPTIONAL
        assert not suggestion.pinch_up

    def test_avoids_the_last_site_even_when_it_is_outside_its_window(self) -> None:
        result = run(history=(dose(ABDOMEN_LEFT, 1, 200), dose(ABDOMEN_RIGHT, 1, 100)))
        assert suggested_site(result) is ABDOMEN_LEFT
        row = status_of(result, ABDOMEN_LEFT)
        assert row.last_spot == 1
        assert row.state is SiteState.SUGGESTED

    def test_advances_the_spot_of_the_chosen_site_from_its_last_spot(self) -> None:
        result = run(history=(dose(ABDOMEN_LEFT, 1, 30), dose(ABDOMEN_RIGHT, 2, 50)))
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_RIGHT, 3)
        assert ReasonCode.ROTATE_NEXT in result.suggestion.reason_codes

    def test_wraps_the_spot_from_4_back_to_1(self) -> None:
        result = run(history=(dose(ABDOMEN_LEFT, 4, 60), dose(ABDOMEN_RIGHT, 2, 30)))
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_LEFT, 1)

    def test_reports_the_last_use_and_spot_of_every_site(self) -> None:
        result = run(history=(dose(ABDOMEN_RIGHT, 2, 30), dose(ABDOMEN_RIGHT, 1, 60)))
        row = status_of(result, ABDOMEN_RIGHT)
        assert row.last_spot == 2
        assert row.last_used_at == hours_ago(30)
        other = status_of(result, THIGH_LEFT)
        assert other.last_spot is None
        assert other.last_used_at is None

    def test_takes_the_last_spot_from_the_most_recent_dose_of_a_site(self) -> None:
        result = run(
            history=(
                dose(ABDOMEN_LEFT, 4, 100),
                dose(ABDOMEN_LEFT, 2, 30),
                dose(ABDOMEN_RIGHT, 1, 60),
            )
        )
        row = status_of(result, ABDOMEN_LEFT)
        assert row.last_spot == 2
        assert row.last_used_at == hours_ago(30)


def test_a_dose_with_a_site_but_no_spot_still_rotates_and_restarts_at_spot_1() -> None:
    unspotted = InjectionHistoryEntry(
        site=ABDOMEN_LEFT, spot=None, kind=BOLUS, administered_at=hours_ago(30)
    )
    result = run(history=(dose(ABDOMEN_RIGHT, 2, 10), unspotted))

    assert result.suggestion is not None
    assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_LEFT, 1)
    assert status_of(result, ABDOMEN_LEFT).last_spot is None


class TestRotationPerInsulinFamily:
    def test_keeps_the_bolus_opposite_the_last_bolus_after_a_basal_on_the_thigh(
        self,
    ) -> None:
        result = run(
            history=(dose(ABDOMEN_LEFT, 1, 12), dose(THIGH_RIGHT, 1, 9.5, BASAL))
        )
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_RIGHT, 1)

    def test_does_not_repeat_the_last_bolus_side_when_a_basal_came_last(self) -> None:
        result = run(
            history=(
                dose(ABDOMEN_RIGHT, 1, 12),
                dose(ABDOMEN_LEFT, 1, 3),
                dose(THIGH_RIGHT, 1, 1, BASAL),
            )
        )
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_RIGHT, 2)

    def test_the_basal_does_not_repeat_the_last_basal_thigh_after_a_bolus(self) -> None:
        result = run(
            kind=BASAL,
            history=(
                dose(THIGH_RIGHT, 1, 40, BASAL),
                dose(THIGH_LEFT, 1, 12, BASAL),
                dose(ABDOMEN_RIGHT, 1, 2),
            ),
        )
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (THIGH_RIGHT, 2)


class TestRecentSitesAreAStateNotAnExclusion:
    def test_keeps_a_bolus_on_the_abdomen_when_the_other_side_was_used_lately(
        self,
    ) -> None:
        # Both abdomen sides are inside 24 h; the right was last, so the left wins.
        result = run(history=(dose(ABDOMEN_LEFT, 1, 12), dose(ABDOMEN_RIGHT, 1, 3)))
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_LEFT, 2)
        assert status_of(result, ABDOMEN_LEFT).state is SiteState.SUGGESTED
        assert status_of(result, ABDOMEN_RIGHT).state is SiteState.RECENT
        assert set(result.suggestion.reason_codes) >= {
            ReasonCode.FASTEST_ABSORPTION,
            ReasonCode.ROTATE_NEXT,
        }


class TestRecentWindows:
    def test_marks_a_site_used_23_hours_ago_as_recent_for_a_bolus(self) -> None:
        result = run(history=(dose(ABDOMEN_RIGHT, 1, 23),))
        row = status_of(result, ABDOMEN_RIGHT)
        assert row.state is SiteState.RECENT
        assert row.reason_code is ReasonCode.RECENTLY_USED
        assert suggested_site(result) is ABDOMEN_LEFT

    def test_releases_a_rapid_site_after_25_hours(self) -> None:
        result = run(history=(dose(ABDOMEN_RIGHT, 1, 25),))
        assert status_of(result, ABDOMEN_RIGHT).state is SiteState.ALLOWED

    def test_the_rapid_window_is_strict(self) -> None:
        result = run(history=(dose(ABDOMEN_RIGHT, 1, 24),))
        assert status_of(result, ABDOMEN_RIGHT).state is SiteState.ALLOWED

    def test_keeps_a_basal_site_recent_for_72_hours_and_releases_it_after_80(
        self,
    ) -> None:
        inside = run(kind=BASAL, history=(dose(THIGH_RIGHT, 1, 50, BASAL),))
        assert status_of(inside, THIGH_RIGHT).state is SiteState.RECENT
        outside = run(kind=BASAL, history=(dose(THIGH_RIGHT, 1, 80, BASAL),))
        assert status_of(outside, THIGH_RIGHT).state is SiteState.ALLOWED

    def test_uses_the_window_of_the_dose_kind_not_the_requested_one(self) -> None:
        result = run(kind=BASAL, history=(dose(THIGH_RIGHT, 1, 10, BOLUS),))
        assert status_of(result, THIGH_RIGHT).state is SiteState.RECENT
        basal_then_bolus = run(history=(dose(ABDOMEN_RIGHT, 1, 30, BASAL),))
        assert status_of(basal_then_bolus, ABDOMEN_RIGHT).state is SiteState.RECENT

    def test_still_answers_when_the_only_eligible_site_is_the_one_used_last(
        self,
    ) -> None:
        result = run(plan=(ABDOMEN_RIGHT,), history=(dose(ABDOMEN_RIGHT, 2, 2),))
        assert result.suggestion is not None
        assert (result.suggestion.site, result.suggestion.spot) == (ABDOMEN_RIGHT, 3)
        assert status_of(result, ABDOMEN_RIGHT).state is SiteState.SUGGESTED


def test_returns_no_suggestion_when_every_site_is_avoided_and_keeps_the_reasons() -> (
    None
):
    result = run(plan=(ARM_LEFT,), who=profile(lipohypertrophy=(lipo(ARM_LEFT, 5),)))
    assert result.suggestion is None
    assert not [row for row in result.sites if row.state is SiteState.SUGGESTED]
    row = status_of(result, ARM_LEFT)
    assert row.state is SiteState.AVOID
    assert row.reason_code is ReasonCode.LIPOHYPERTROPHY_REPORTED


class TestNeedleNote:
    def test_uses_the_pinch_for_a_patient_under_18(self) -> None:
        result = run(who=profile(birth_date=date(2012, 5, 1)))
        assert result.suggestion is not None
        assert result.suggestion.needle_note is NeedleNote.PINCH_UP
        assert result.suggestion.pinch_up

    def test_does_not_use_the_pinch_for_an_adult_in_range(self) -> None:
        result = run(who=profile(birth_date=date(2008, 11, 19)))
        assert result.suggestion is not None
        assert result.suggestion.needle_note is NeedleNote.PINCH_OPTIONAL
        assert not result.suggestion.pinch_up

    def test_uses_the_pinch_for_the_lean(self) -> None:
        result = run(who=profile(bmi=Decimal("18.5")))
        assert result.suggestion is not None
        assert result.suggestion.pinch_up

    def test_a_missing_birth_date_is_not_a_minor(self) -> None:
        result = run(who=profile(birth_date=None))
        assert result.suggestion is not None
        assert not result.suggestion.pinch_up


class TestDeterminismAndShape:
    def test_gives_the_same_answer_for_the_same_input(self) -> None:
        rule_input = InjectionRuleInput(
            kind=BOLUS,
            now=NOW,
            profile=WOMAN,
            plan=None,
            history=(dose(ABDOMEN_RIGHT, 1, 30),),
        )
        assert STRATEGY.suggest(rule_input) == STRATEGY.suggest(rule_input)

    def test_lists_the_eight_sites_once_each_in_canonical_order(self) -> None:
        result = run(history=(dose(ABDOMEN_RIGHT, 1, 5),))
        assert [row.site for row in result.sites] == list(SITE_ORDER)
        assert len(result.sites) == len(SiteCode)

    def test_never_carries_units(self) -> None:
        # The answer has no field that could hold an insulin amount.
        names = set(InjectionSites.__dataclass_fields__)
        assert names == {"kind", "suggestion", "sites", "rules_version"}


class TestInvariantsOverTheWholeGrid:
    sexes: ClassVar[list[Sex]] = list(Sex)
    bmis: tuple[Decimal | None, ...] = (
        None,
        Decimal("18.5"),
        Decimal("21.5"),
        Decimal(22),
        Decimal(25),
    )
    pregnancies: ClassVar[list[PregnancyStatus]] = list(PregnancyStatus)
    kinds: ClassVar[list[InsulinKind]] = list(InsulinKind)
    plans: tuple[tuple[SiteCode, ...] | None, ...] = (
        None,
        (ABDOMEN_LEFT,),
        (THIGH_RIGHT, ARM_LEFT, ABDOMEN_RIGHT),
        (),
    )
    histories: tuple[tuple[InjectionHistoryEntry, ...], ...] = (
        (),
        (dose(ABDOMEN_RIGHT, 1, 5),),
        (
            dose(ABDOMEN_RIGHT, 4, 40),
            dose(ABDOMEN_LEFT, 2, 70),
            dose(THIGH_RIGHT, 1, 20, BASAL),
        ),
        (
            dose(THIGH_LEFT, 3, 30, BASAL),
            dose(BUTTOCK_LEFT, 4, 200, BASAL),
            dose(ABDOMEN_LEFT, 4, 90),
        ),
    )
    lipos: tuple[tuple[LipohypertrophyReport, ...], ...] = (
        (),
        (lipo(ABDOMEN_LEFT, 10),),
        (lipo(ARM_RIGHT, 30), lipo(THIGH_LEFT, 200)),
    )

    def test_always_gives_one_suggested_site_or_none_and_keeps_every_rule(
        self,
    ) -> None:
        checked = 0
        grid = product(
            self.sexes,
            self.bmis,
            self.pregnancies,
            self.kinds,
            self.plans,
            self.histories,
            self.lipos,
        )
        for sex, bmi, pregnancy, kind, plan, history, reports in grid:
            who = profile(
                sex=sex,
                bmi=bmi,
                pregnancy=pregnancy,
                lipohypertrophy=reports,
                birth_date=date(1990, 1, 1),
            )
            result = run(kind=kind, who=who, plan=plan, history=history)
            checked += 1
            suggested = [
                row for row in result.sites if row.state is SiteState.SUGGESTED
            ]
            assert len(result.sites) == len(SiteCode)
            if result.suggestion is None:
                assert not suggested
                continue
            site, spot = result.suggestion.site, result.suggestion.spot
            assert [row.site for row in suggested] == [site]
            assert 1 <= spot <= 4
            if plan is not None:
                assert site in plan
            active = [r for r in reports if NOW - r.reported_at <= NINETY_DAYS]
            assert all(report.site is not site for report in active)
            bolus = kind in {BOLUS, CORRECTION}
            if bolus and is_lean(sex, bmi) and plan is None:
                assert not site.value.startswith(("ARM_", "THIGH_"))
            if pregnancy is PregnancyStatus.PREGNANT and site.value.startswith(
                "ABDOMEN_"
            ):
                assert spot in {3, 4}
            assert result.suggestion.pinch_up is is_lean(sex, bmi)
        assert checked == (
            len(self.sexes)
            * len(self.bmis)
            * len(self.pregnancies)
            * len(self.kinds)
            * len(self.plans)
            * len(self.histories)
            * len(self.lipos)
        )
