"""``GET /patients/own/injection-sites``: gathers the input and asks the rule."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from insumap.application.monitoring.injection import (
    GetOwnInjectionSitesUseCase,
    sites_allowed_by_plan,
)
from insumap.domain.identity.errors import ConsentRequiredError, PermissionDeniedError
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.monitoring.injection_rule import (
    InjectionHistoryEntry,
    InjectionRulesV1Strategy,
    LipohypertrophyReport,
)
from insumap.domain.monitoring.injection_sites import (
    PregnancyStatus,
    ReasonCode,
    SiteCode,
    SiteState,
)
from insumap.domain.monitoring.records import InsulinKind
from tests.support.monitoring_factories import NOW, PATIENT_ID
from tests.support.monitoring_fakes import RecordsWorld, patient_actor
from tests.support.treatment_fakes import FakePlans, active
from tests.unit.domain.treatment.factories import draft, insulin, measure, plan_items


@pytest.fixture
def world() -> RecordsWorld:
    return RecordsWorld()


def use_case(
    world: RecordsWorld, plans: FakePlans | None = None
) -> GetOwnInjectionSitesUseCase:
    return GetOwnInjectionSitesUseCase(
        uow=world.uow,
        gate=world.own_gate,
        profiles=world.body_profiles,
        history=world.injection_history,
        plans=plans or FakePlans(),
        strategy=InjectionRulesV1Strategy(),
        clock=world.clock,
    )


def test_a_new_patient_gets_the_abdomen_for_a_bolus(world: RecordsWorld) -> None:
    answer = use_case(world).execute(patient_actor(), InsulinKind.BOLUS)

    assert answer.suggestion is not None
    assert answer.suggestion.site is SiteCode.ABDOMEN_RIGHT
    assert answer.rules_version == "injection-rules-1"
    assert world.uow.commits == 1


def test_the_latest_doses_decide_the_rotation(world: RecordsWorld) -> None:
    world.injection_history.doses.append(
        InjectionHistoryEntry(
            site=SiteCode.ABDOMEN_RIGHT,
            spot=2,
            kind=InsulinKind.BOLUS,
            administered_at=NOW - timedelta(hours=30),
        )
    )

    answer = use_case(world).execute(patient_actor(), InsulinKind.BOLUS)

    assert answer.suggestion is not None
    assert answer.suggestion.site is SiteCode.ABDOMEN_LEFT


def test_a_lipohypertrophy_report_inside_90_days_avoids_the_site(
    world: RecordsWorld,
) -> None:
    world.injection_history.reports.append(
        LipohypertrophyReport(
            site=SiteCode.ABDOMEN_RIGHT, reported_at=NOW - timedelta(days=10)
        )
    )
    world.injection_history.reports.append(
        LipohypertrophyReport(
            site=SiteCode.ABDOMEN_LEFT, reported_at=NOW - timedelta(days=91)
        )
    )

    answer = use_case(world).execute(patient_actor(), InsulinKind.BOLUS)

    rows = {row.site: row for row in answer.sites}
    assert (
        rows[SiteCode.ABDOMEN_RIGHT].reason_code is ReasonCode.LIPOHYPERTROPHY_REPORTED
    )
    assert rows[SiteCode.ABDOMEN_LEFT].state is not SiteState.AVOID


def test_the_body_profile_changes_the_answer(world: RecordsWorld) -> None:
    assert world.body_profiles.profile is not None
    world.body_profiles.profile = replace(
        world.body_profiles.profile,
        bmi=Decimal("18.0"),
        pregnancy_status=PregnancyStatus.PREGNANT,
    )

    answer = use_case(world).execute(patient_actor(), InsulinKind.BOLUS)

    assert answer.suggestion is not None
    assert answer.suggestion.spot == 3
    assert answer.suggestion.pinch_up


def test_the_active_plan_restricts_the_sites_of_that_kind(world: RecordsWorld) -> None:
    plans = FakePlans()
    restricted = replace(
        insulin("Basal"),
        injection_sites=(SiteCode.BUTTOCK_LEFT, SiteCode.ARM_RIGHT),
    )
    plan = replace(
        draft(*plan_items(restricted, measure())),
        patient_id=PATIENT_ID,
    )
    plans.rows[plan.plan_id] = active(plan)

    answer = use_case(world, plans).execute(patient_actor(), InsulinKind.BASAL)

    assert answer.suggestion is not None
    assert answer.suggestion.site is SiteCode.BUTTOCK_LEFT
    # A bolus is not restricted by an item of another kind.
    bolus = use_case(world, plans).execute(patient_actor(), InsulinKind.BOLUS)
    assert bolus.suggestion is not None
    assert bolus.suggestion.site is SiteCode.ABDOMEN_RIGHT


def test_plan_items_of_other_kinds_and_without_plan_do_not_restrict() -> None:
    assert sites_allowed_by_plan(None, InsulinKind.BASAL) is None
    plan = draft(*plan_items(insulin("Basal")))
    assert sites_allowed_by_plan(plan, InsulinKind.BASAL) is None


def test_without_the_permission_nothing_is_read(world: RecordsWorld) -> None:
    with pytest.raises(PermissionDeniedError):
        use_case(world).execute(
            patient_actor(permissions=frozenset({PermissionCode.RECORDS_WRITE_OWN})),
            InsulinKind.BOLUS,
        )


def test_without_a_current_consent_it_is_refused(world: RecordsWorld) -> None:
    world.consents.accepted = False

    with pytest.raises(ConsentRequiredError):
        use_case(world).execute(patient_actor(), InsulinKind.BOLUS)
