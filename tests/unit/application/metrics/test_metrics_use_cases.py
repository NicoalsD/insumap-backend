"""Metrics and AGP use cases: periods, previous window, access and sufficiency."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from insumap.application.metrics.metrics import (
    AgpInput,
    ComputeGlycemicMetricsUseCase,
    GetAgpUseCase,
    MetricsInput,
    MetricWindow,
    period_of,
    previous_period,
)
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.metrics.agp import AgpResolution
from insumap.domain.metrics.glycemic_metrics import Confidence, Signal
from insumap.domain.metrics.target_strategy import GlycemicTargetStrategyRegistry
from insumap.domain.monitoring.glucose import ReadingSource
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.metrics_factories import series
from tests.support.monitoring_factories import NOW, PATIENT_ID
from tests.support.monitoring_fakes import (
    OTHER_PATIENT_ID,
    TEST_PROFILE,
    RecordsWorld,
    doctor_actor,
    patient_actor,
)

BOGOTA = ZoneInfo("America/Bogota")
TODAY_BOGOTA = datetime(2026, 11, 19, 0, 0, tzinfo=BOGOTA)  # NOW is 07:00 local


def metrics_case(world: RecordsWorld) -> ComputeGlycemicMetricsUseCase:
    return ComputeGlycemicMetricsUseCase(
        uow=world.uow,
        own_gate=world.own_gate,
        assigned_gate=world.assigned_gate,
        targets=world.targets,
        series=world.series,
        strategies=GlycemicTargetStrategyRegistry(),
        clock=world.clock,
    )


def agp_case(world: RecordsWorld) -> GetAgpUseCase:
    return GetAgpUseCase(
        uow=world.uow,
        own_gate=world.own_gate,
        assigned_gate=world.assigned_gate,
        targets=world.targets,
        series=world.series,
        clock=world.clock,
    )


def fill(
    world: RecordsWorld,
    days: int,
    value: int = 120,
    *,
    ending: datetime = TODAY_BOGOTA,
    source: ReadingSource = ReadingSource.CGM,
) -> None:
    start = ending - timedelta(days=days)
    points = series(start, [value] * (days * 288), interval_min=5, source=source)
    world.series.points_by_patient.setdefault(PATIENT_ID, []).extend(points)


@pytest.fixture
def world() -> RecordsWorld:
    return RecordsWorld()


def test_the_period_of_n_days_ends_at_the_start_of_today_local() -> None:
    period = period_of(MetricWindow.LAST_14_DAYS, NOW, BOGOTA)

    assert period.end == TODAY_BOGOTA
    assert period.start == TODAY_BOGOTA - timedelta(days=14)
    previous = previous_period(period)
    assert previous.end == period.start
    assert previous.start == TODAY_BOGOTA - timedelta(days=28)


def test_the_24_hour_window_rolls_up_to_now_and_its_previous_is_the_day_before() -> (
    None
):
    period = period_of(MetricWindow.LAST_24_HOURS, NOW, BOGOTA)

    assert period.end == NOW
    assert period.end.astimezone(NOW.tzinfo) - period.start.astimezone(NOW.tzinfo) == (
        timedelta(hours=24)
    )
    assert previous_period(period).end == period.start


def test_the_own_metrics_use_the_profile_of_the_patient(world: RecordsWorld) -> None:
    fill(world, 14)

    result = metrics_case(world).execute(MetricsInput(actor=patient_actor()))

    assert result.metrics.signal is Signal.CGM
    assert result.metrics.tir_pct == Decimal("100.00")
    assert result.metrics.is_sufficient
    assert result.metrics.confidence is Confidence.NORMAL
    assert (result.profile.id, result.profile.code, result.profile.version) == (
        TEST_PROFILE.id,
        TEST_PROFILE.code,
        3,
    )
    assert result.timezone == "America/Bogota"
    assert result.strategy_code == "ADULT_STANDARD"
    assert result.on_target is True
    assert result.period_to == TODAY_BOGOTA


def test_the_previous_window_and_the_signed_tir_delta(world: RecordsWorld) -> None:
    fill(world, 14, 120)  # the current 14 days: all in range
    fill(world, 14, 300, ending=TODAY_BOGOTA - timedelta(days=14))  # previous: high

    result = metrics_case(world).execute(MetricsInput(actor=patient_actor()))

    assert result.previous is not None
    assert result.previous.tir_pct == Decimal("0.00")
    assert result.tir_delta_pct == Decimal("100.00")


def test_a_negative_delta_keeps_its_sign(world: RecordsWorld) -> None:
    fill(world, 14, 300)
    fill(world, 14, 120, ending=TODAY_BOGOTA - timedelta(days=14))

    result = metrics_case(world).execute(MetricsInput(actor=patient_actor()))

    assert result.tir_delta_pct == Decimal("-100.00")
    assert result.on_target is False


def test_without_comparison_there_is_no_previous(world: RecordsWorld) -> None:
    fill(world, 14)

    result = metrics_case(world).execute(
        MetricsInput(actor=patient_actor(), compare_previous=False)
    )

    assert result.previous is None
    assert result.tir_delta_pct is None


def test_todays_partial_day_is_left_out_of_a_day_window(world: RecordsWorld) -> None:
    fill(world, 7, 120)
    world.series.points_by_patient[PATIENT_ID] += series(
        TODAY_BOGOTA, [400] * 20, interval_min=5
    )

    result = metrics_case(world).execute(
        MetricsInput(actor=patient_actor(), window=MetricWindow.LAST_7_DAYS)
    )

    assert result.metrics.tir_pct == Decimal("100.00")


def test_a_patient_without_data_says_so_instead_of_inventing_a_percentage(
    world: RecordsWorld,
) -> None:
    result = metrics_case(world).execute(MetricsInput(actor=patient_actor()))

    assert result.metrics.tir_pct is None
    assert not result.metrics.is_sufficient
    assert result.metrics.confidence is Confidence.LOW_CONFIDENCE
    assert result.on_target is None


def test_a_doctor_reads_an_assigned_patient(world: RecordsWorld) -> None:
    fill(world, 14)

    result = metrics_case(world).execute(
        MetricsInput(actor=doctor_actor(), patient_id=PATIENT_ID)
    )

    assert result.metrics.tir_pct == Decimal("100.00")
    assert world.patients.reads[0][1] == PATIENT_ID
    assert world.uow.commits == 1  # the audit row of the read is kept


def test_an_unassigned_patient_is_not_found_and_a_missing_permission_forbidden(
    world: RecordsWorld,
) -> None:
    with pytest.raises(InsumapError) as caught:
        metrics_case(world).execute(
            MetricsInput(actor=doctor_actor(), patient_id=OTHER_PATIENT_ID)
        )
    assert caught.value.code is ErrorCode.NOT_FOUND
    with pytest.raises(PermissionDeniedError):
        metrics_case(world).execute(
            MetricsInput(
                actor=doctor_actor(permissions=frozenset()), patient_id=PATIENT_ID
            )
        )
    with pytest.raises(PermissionDeniedError):
        metrics_case(world).execute(
            MetricsInput(actor=patient_actor(permissions=frozenset()))
        )


def test_the_profile_must_exist(world: RecordsWorld) -> None:
    world.targets.targets = None

    with pytest.raises(InsumapError) as caught:
        metrics_case(world).execute(MetricsInput(actor=patient_actor()))

    assert caught.value.code is ErrorCode.INTERNAL_ERROR


def test_the_agp_has_bins_and_the_range_of_the_profile(world: RecordsWorld) -> None:
    fill(world, 14)

    result = agp_case(world).execute(AgpInput(actor=patient_actor()))

    assert result.is_sufficient
    assert len(result.bins) == 24
    assert result.range_low_mg_dl == TEST_PROFILE.range_low_mg_dl
    assert result.range_high_mg_dl == TEST_PROFILE.range_high_mg_dl
    fine = agp_case(world).execute(
        AgpInput(actor=patient_actor(), resolution=AgpResolution.QUARTER)
    )
    assert len(fine.bins) == 96


def test_the_agp_days_default_to_the_profile_reference_period(
    world: RecordsWorld,
) -> None:
    fill(world, 3)

    default = agp_case(world).execute(AgpInput(actor=patient_actor()))
    three_days = agp_case(world).execute(AgpInput(actor=patient_actor(), days=3))

    assert not default.is_sufficient  # 3 of the profile's 14 days
    assert three_days.is_sufficient


def test_with_insufficient_data_the_agp_has_no_bins(world: RecordsWorld) -> None:
    fill(world, 5)

    result = agp_case(world).execute(AgpInput(actor=patient_actor()))

    assert result.bins == ()
    assert not result.is_sufficient
    assert Decimal(0) < result.data_sufficiency_pct < Decimal(70)


def test_fingersticks_have_no_agp(world: RecordsWorld) -> None:
    world.series.points_by_patient[PATIENT_ID] = series(
        TODAY_BOGOTA - timedelta(days=14),
        [100] * 14 * 288,
        source=ReadingSource.SMBG,
    )

    result = agp_case(world).execute(AgpInput(actor=patient_actor()))

    assert result.bins == ()
    assert not result.is_sufficient


def test_a_doctor_reads_the_agp_of_an_assigned_patient(world: RecordsWorld) -> None:
    fill(world, 14)

    result = agp_case(world).execute(
        AgpInput(actor=doctor_actor(), patient_id=PATIENT_ID)
    )

    assert result.bins
