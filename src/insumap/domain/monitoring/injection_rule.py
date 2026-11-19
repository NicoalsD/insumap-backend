"""Where to inject next: a pure, deterministic rule (never a dose).

The rule answers a question about the place, not about the amount: no unit of
insulin goes in or out of it. It reads the profile of the patient, the sites the
plan allows and the recent history, and it never reads the clock (the caller
passes ``now``).

The thresholds below are general injection technique that the clinical team
validates; they are pinned by ``RULES_VERSION`` and listed here, not scattered.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final, final, override

from insumap.domain.monitoring.injection_sites import (
    ALL_SPOTS,
    SITE_ORDER,
    NeedleNote,
    PregnancyStatus,
    ReasonCode,
    SiteCode,
    SiteGroup,
    SiteState,
)
from insumap.domain.monitoring.records import InsulinKind
from insumap.domain.onboarding.vocabulary import Sex

RULES_VERSION: Final = "injection-rules-1"

# Rapid insulin: a site used in the last 24 h is recent. Basal: 72 h.
RAPID_RECENT_WINDOW: Final = timedelta(hours=24)
BASAL_RECENT_WINDOW: Final = timedelta(hours=72)
# A lipohypertrophy symptom blocks its site for 90 days after it was reported.
LIPOHYPERTROPHY_LOOKBACK: Final = timedelta(days=90)
# Lean: BMI under 20, or a man under 22.
LEAN_BMI: Final = Decimal(20)
LEAN_BMI_MALE: Final = Decimal(22)
MINOR_AGE_YEARS: Final = 18
# Pregnancy: the center of the abdomen is left out, so only the lateral spots are used.
PREGNANCY_ABDOMEN_SPOTS: Final[tuple[int, ...]] = (3, 4)

LIMB_GROUPS: Final = frozenset({SiteGroup.ARM, SiteGroup.THIGH})

# Lower rank is preferred. Bolus, correction and mixed: abdomen first
# (fastest absorption).
RAPID_ORDER: Final = {
    SiteGroup.ABDOMEN: 0,
    SiteGroup.THIGH: 1,
    SiteGroup.BUTTOCK: 2,
    SiteGroup.ARM: 3,
}
# Basal: thigh, then buttock (steady absorption). Women and other or unknown sex.
BASAL_ORDER: Final = {
    SiteGroup.THIGH: 0,
    SiteGroup.BUTTOCK: 1,
    SiteGroup.ABDOMEN: 2,
    SiteGroup.ARM: 3,
}
# Basal in men: abdomen and buttock first.
BASAL_ORDER_MALE: Final = {
    SiteGroup.ABDOMEN: 0,
    SiteGroup.BUTTOCK: 1,
    SiteGroup.THIGH: 2,
    SiteGroup.ARM: 3,
}


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionHistoryEntry:
    """A dose already recorded with its site. Doses without a site do not rotate."""

    site: SiteCode
    spot: int
    kind: InsulinKind
    administered_at: datetime


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class LipohypertrophyReport:
    """A lipohypertrophy symptom the patient reported on a site."""

    site: SiteCode
    reported_at: datetime


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionPatientProfile:
    """What the rule needs to know about the patient."""

    sex: Sex
    birth_date: date | None
    bmi: Decimal | None
    pregnancy: PregnancyStatus
    lipohypertrophy: tuple[LipohypertrophyReport, ...] = ()


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionRuleInput:
    """One question: where does the next ``kind`` injection go?

    ``plan`` is the sites the plan allows for this kind, or ``None`` when the plan
    does not restrict them.
    """

    kind: InsulinKind
    now: datetime
    profile: InjectionPatientProfile
    plan: tuple[SiteCode, ...] | None
    history: tuple[InjectionHistoryEntry, ...]


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionSuggestion:
    """The single site and spot the patient should use now."""

    site: SiteCode
    spot: int
    reason_codes: tuple[ReasonCode, ...]
    needle_note: NeedleNote
    pinch_up: bool


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionSiteStatus:
    """The state of one site, with its last use."""

    site: SiteCode
    state: SiteState
    reason_code: ReasonCode | None
    last_used_at: datetime | None
    last_spot: int | None


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class InjectionSites:
    """The answer: ``suggestion`` is ``None`` only when every site is avoided."""

    kind: InsulinKind
    suggestion: InjectionSuggestion | None
    sites: tuple[InjectionSiteStatus, ...]
    rules_version: str


def age_in_years(birth_date: date, now: datetime) -> int:
    """Whole years between the birth date and ``now``, counted on the UTC date."""
    today = now.astimezone(UTC).date()
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def is_lean(sex: Sex, bmi: Decimal | None) -> bool:
    """Lean: BMI under 20, or a man under 22. An unknown BMI is never lean."""
    if bmi is None:
        return False
    return bmi < LEAN_BMI or (sex is Sex.MALE and bmi < LEAN_BMI_MALE)


def plan_sites_for(
    restrictions: Iterable[tuple[SiteCode, ...] | None],
) -> tuple[SiteCode, ...] | None:
    """Sites the plan allows for one kind, from the restriction of each of its items.

    Items with a restriction must all allow the site (intersection); items without
    one do not restrict. ``None`` when nothing restricts.
    """
    found = [sites for sites in restrictions if sites is not None]
    if not found:
        return None
    return tuple(
        site for site in SITE_ORDER if all(site in allowed for allowed in found)
    )


def _is_rapid_family(kind: InsulinKind) -> bool:
    return kind is not InsulinKind.BASAL


def _recent_window(kind: InsulinKind) -> timedelta:
    return BASAL_RECENT_WINDOW if kind is InsulinKind.BASAL else RAPID_RECENT_WINDOW


@final
@dataclass(frozen=True, slots=True)
class _Classified:
    site: SiteCode
    state: SiteState
    reason: ReasonCode | None
    last: InjectionHistoryEntry | None


class InjectionSiteStrategy(ABC):
    """Chooses the injection site of the next dose.

    Pattern: P19 Strategy. The rule can change (a new ``rules_version``) without
    touching the use case that asks.
    """

    @property
    @abstractmethod
    def rules_version(self) -> str:
        """The version the answer carries, so the app knows which rules spoke."""

    @abstractmethod
    def suggest(self, rule_input: InjectionRuleInput) -> InjectionSites:
        """The suggested site and the state of every site."""


@final
class InjectionRulesV1Strategy(InjectionSiteStrategy):
    """Rules 1 to 5 of the injection-site contract.

    1. Candidates are the sites the plan allows (``None`` = all).
    2. Out: lipohypertrophy in 90 days; plan restriction; for a bolus in a lean
       patient, arms and thighs unless the plan asks for them. Pregnancy keeps
       the abdomen but only spots 3 and 4.
    3. Preference: bolus and correction to the abdomen; basal to thigh, then
       buttock (men: abdomen, buttock first); mixed to the abdomen.
    4. Rotation: never the last site used of the same insulin family while
       another is eligible; prefer a site outside its window, then alternate
       left and right, then the oldest use. Within the site, advance the spot.
       RECENT is a state, not an exclusion.
    5. One ``SUGGESTED``; ``None`` only when no site is eligible.

    Pattern: P19 Strategy
    """

    @property
    @override
    def rules_version(self) -> str:
        return RULES_VERSION

    @override
    def suggest(self, rule_input: InjectionRuleInput) -> InjectionSites:
        kind, now, profile = rule_input.kind, rule_input.now, rule_input.profile
        bolus = kind in {InsulinKind.BOLUS, InsulinKind.CORRECTION}
        pregnant = profile.pregnancy is PregnancyStatus.PREGNANT
        lean = is_lean(profile.sex, profile.bmi)
        minor = (
            profile.birth_date is not None
            and age_in_years(profile.birth_date, now) < MINOR_AGE_YEARS
        )

        last_by_site = _last_by_site(rule_input.history)
        last_site = _last_site_of_family(rule_input.history, kind)

        def classify(site: SiteCode) -> _Classified:
            last = last_by_site.get(site)
            state, reason = self._state_of(
                site=site,
                rule_input=rule_input,
                bolus=bolus,
                lean=lean,
                pregnant=pregnant,
                last=last,
            )
            return _Classified(site, state, reason, last)

        classified = [classify(site) for site in SITE_ORDER]
        eligible = [entry for entry in classified if entry.state is not SiteState.AVOID]
        # Rotation (rule 4): skip the last site used unless it is the only eligible.
        pool = [entry for entry in eligible if entry.site is not last_site]
        candidates = pool or eligible

        order = _order_for(kind, profile.sex)
        last_is_left = None if last_site is None else last_site.is_left

        def rank(entry: _Classified) -> tuple[int, int, int, float, int]:
            same_side = (
                0 if last_is_left is None else int(entry.site.is_left is last_is_left)
            )
            last_used = (
                float("-inf")
                if entry.last is None
                else entry.last.administered_at.timestamp()
            )
            return (
                order[entry.site.group],
                int(entry.state is SiteState.RECENT),
                same_side,
                last_used,
                SITE_ORDER.index(entry.site),
            )

        ranked = sorted(candidates, key=rank)
        if not ranked:
            return InjectionSites(
                kind=kind,
                suggestion=None,
                sites=tuple(_status(entry, None, ()) for entry in classified),
                rules_version=RULES_VERSION,
            )

        chosen = ranked[0]
        group = chosen.site.group
        cycle = (
            PREGNANCY_ABDOMEN_SPOTS
            if pregnant and group is SiteGroup.ABDOMEN
            else ALL_SPOTS
        )
        spot = _next_spot(cycle, 0 if chosen.last is None else chosen.last.spot)

        reasons: list[ReasonCode] = []
        if bolus and group is SiteGroup.ABDOMEN:
            reasons.append(ReasonCode.FASTEST_ABSORPTION)
        if kind is InsulinKind.BASAL and group in {SiteGroup.THIGH, SiteGroup.BUTTOCK}:
            reasons.append(ReasonCode.STEADY_ABSORPTION)
        if pregnant and group is SiteGroup.ABDOMEN:
            reasons.append(ReasonCode.PREGNANCY_AVOID_ABDOMEN_CENTER)
        if chosen.last is not None:
            reasons.append(ReasonCode.ROTATE_NEXT)

        # Pinch up for minors and for the lean.
        pinch_up = minor or lean
        suggestion = InjectionSuggestion(
            site=chosen.site,
            spot=spot,
            reason_codes=tuple(reasons),
            needle_note=NeedleNote.PINCH_UP if pinch_up else NeedleNote.PINCH_OPTIONAL,
            pinch_up=pinch_up,
        )
        return InjectionSites(
            kind=kind,
            suggestion=suggestion,
            sites=tuple(
                _status(entry, chosen.site, tuple(reasons)) for entry in classified
            ),
            rules_version=RULES_VERSION,
        )

    @staticmethod
    def _state_of(
        *,
        site: SiteCode,
        rule_input: InjectionRuleInput,
        bolus: bool,
        lean: bool,
        pregnant: bool,
        last: InjectionHistoryEntry | None,
    ) -> tuple[SiteState, ReasonCode | None]:
        plan, now = rule_input.plan, rule_input.now
        if plan is not None and site not in plan:
            return SiteState.AVOID, ReasonCode.PLAN_RESTRICTED
        if any(
            report.site is site and now - report.reported_at <= LIPOHYPERTROPHY_LOOKBACK
            for report in rule_input.profile.lipohypertrophy
        ):
            return SiteState.AVOID, ReasonCode.LIPOHYPERTROPHY_REPORTED
        # "Unless the plan asks for them": a restricted plan that lists a limb keeps it.
        if plan is None and bolus and lean and site.group in LIMB_GROUPS:
            return SiteState.AVOID, ReasonCode.LEAN_AVOID_LIMBS
        if last is not None and now - last.administered_at < _recent_window(last.kind):
            return SiteState.RECENT, ReasonCode.RECENTLY_USED
        if pregnant and site.group is SiteGroup.ABDOMEN:
            return SiteState.ALLOWED, ReasonCode.PREGNANCY_AVOID_ABDOMEN_CENTER
        return SiteState.ALLOWED, None


def _last_by_site(
    history: Sequence[InjectionHistoryEntry],
) -> dict[SiteCode, InjectionHistoryEntry]:
    """The most recent dose of every site, whatever its kind."""
    found: dict[SiteCode, InjectionHistoryEntry] = {}
    for dose in history:
        current = found.get(dose.site)
        if current is None or dose.administered_at > current.administered_at:
            found[dose.site] = dose
    return found


def _last_site_of_family(
    history: Sequence[InjectionHistoryEntry], kind: InsulinKind
) -> SiteCode | None:
    """Rotation runs per insulin family: rapid (bolus, correction, mixed) or basal."""
    latest: InjectionHistoryEntry | None = None
    for dose in history:
        if _is_rapid_family(dose.kind) != _is_rapid_family(kind):
            continue
        if latest is None or dose.administered_at > latest.administered_at:
            latest = dose
    return None if latest is None else latest.site


def _order_for(kind: InsulinKind, sex: Sex) -> dict[SiteGroup, int]:
    if kind is not InsulinKind.BASAL:
        return RAPID_ORDER
    return BASAL_ORDER_MALE if sex is Sex.MALE else BASAL_ORDER


def _next_spot(cycle: Sequence[int], last_spot: int) -> int:
    """The next spot: 1 to 4 and back to 1; in pregnancy the abdomen cycles 3, 4."""
    return next((spot for spot in cycle if spot > last_spot), cycle[0])


def _status(
    entry: _Classified, suggested: SiteCode | None, reasons: tuple[ReasonCode, ...]
) -> InjectionSiteStatus:
    """The suggested site shows the first reason of the suggestion."""
    is_suggested = entry.site is suggested
    return InjectionSiteStatus(
        site=entry.site,
        state=SiteState.SUGGESTED if is_suggested else entry.state,
        reason_code=(reasons[0] if reasons else None) if is_suggested else entry.reason,
        last_used_at=None if entry.last is None else entry.last.administered_at,
        last_spot=None if entry.last is None else entry.last.spot,
    )
