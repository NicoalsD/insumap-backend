"""Forecast: the AI is optional, the answer is never a 5xx and never a dose."""

from dataclasses import fields
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from insumap.application.metrics.forecast import (
    AiUnavailableError,
    FallbackReason,
    ForecastExplanation,
    ForecastInput,
    ForecastMode,
    ForecastPoint,
    GetForecastUseCase,
    GlucoseForecast,
    GlucoseForecastPort,
    Trend,
)
from insumap.domain.identity.errors import PermissionDeniedError
from insumap.domain.monitoring.glucose import ReadingSource
from insumap.infrastructure.ai.unconfigured_forecast import (
    UnconfiguredGlucoseForecastAdapter,
)
from insumap.shared.errors import ErrorCode, InsumapError
from tests.support.metrics_factories import series
from tests.support.monitoring_factories import NOW, PATIENT_ID
from tests.support.monitoring_fakes import (
    OTHER_PATIENT_ID,
    RecordsWorld,
    doctor_actor,
    patient_actor,
)


class FakeForecasts(GlucoseForecastPort):
    def __init__(self) -> None:
        self.calls = 0
        self.error: AiUnavailableError | None = None

    def forecast(
        self, patient_id: UUID, mode: ForecastMode, now: datetime, zone: ZoneInfo
    ) -> GlucoseForecast:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return GlucoseForecast(
            mode=mode,
            generated_at=now,
            model_name="chronos",
            model_version="1",
            is_fallback=False,
            fallback_reason=None,
            trend=Trend.FALLING,
            points=(
                ForecastPoint(
                    horizon_minutes=30,
                    timestamp=now + timedelta(minutes=30),
                    p10=Decimal(90),
                    p50=Decimal(110),
                    p90=Decimal(140),
                ),
            ),
            risk=(),
            explanation=ForecastExplanation(summary="x", factors=(), data_refs=()),
        )


@pytest.fixture
def world() -> RecordsWorld:
    world = RecordsWorld()
    # 24 hours of sensor readings up to now: enough data for a forecast.
    start = NOW - timedelta(hours=24)
    world.series.points_by_patient[PATIENT_ID] = series(start, [120] * 288)
    return world


def use_case(world: RecordsWorld, forecasts: GlucoseForecastPort) -> GetForecastUseCase:
    return GetForecastUseCase(
        uow=world.uow,
        own_gate=world.own_gate,
        assigned_gate=world.assigned_gate,
        targets=world.targets,
        series=world.series,
        forecasts=forecasts,
        clock=world.clock,
    )


def test_a_forecast_of_the_ai_passes_through(world: RecordsWorld) -> None:
    ai = FakeForecasts()

    result = use_case(world, ai).execute(ForecastInput(actor=patient_actor()))

    assert not result.is_fallback
    assert result.trend is Trend.FALLING
    assert ai.calls == 1


@pytest.mark.parametrize(
    "reason",
    [FallbackReason.AI_TIMEOUT, FallbackReason.CIRCUIT_OPEN, FallbackReason.AI_ERROR],
)
def test_an_ai_failure_is_a_fallback_with_its_reason_never_an_error(
    world: RecordsWorld, reason: FallbackReason
) -> None:
    ai = FakeForecasts()
    ai.error = AiUnavailableError(reason)

    result = use_case(world, ai).execute(ForecastInput(actor=patient_actor()))

    assert result.is_fallback
    assert result.fallback_reason is reason
    assert result.points == ()


def test_the_unconfigured_adapter_answers_the_ai_error_fallback(
    world: RecordsWorld,
) -> None:
    result = use_case(world, UnconfiguredGlucoseForecastAdapter()).execute(
        ForecastInput(actor=patient_actor(), mode=ForecastMode.OVERNIGHT)
    )

    assert result.is_fallback
    assert result.fallback_reason is FallbackReason.AI_ERROR
    assert result.mode is ForecastMode.OVERNIGHT


def test_with_insufficient_data_the_ai_is_not_called(world: RecordsWorld) -> None:
    world.series.points_by_patient[PATIENT_ID] = series(
        NOW - timedelta(hours=3), [120] * 36
    )
    ai = FakeForecasts()

    result = use_case(world, ai).execute(ForecastInput(actor=patient_actor()))

    assert result.fallback_reason is FallbackReason.INSUFFICIENT_DATA
    assert ai.calls == 0


def test_a_patient_with_fingersticks_has_no_forecast(world: RecordsWorld) -> None:
    world.series.points_by_patient[PATIENT_ID] = series(
        NOW - timedelta(hours=24), [120] * 288, source=ReadingSource.SMBG
    )
    ai = FakeForecasts()

    result = use_case(world, ai).execute(ForecastInput(actor=patient_actor()))

    assert result.fallback_reason is FallbackReason.INSUFFICIENT_DATA
    assert ai.calls == 0


def test_a_doctor_needs_the_assignment_and_the_permission(world: RecordsWorld) -> None:
    ai = FakeForecasts()
    assigned = use_case(world, ai).execute(
        ForecastInput(actor=doctor_actor(), patient_id=PATIENT_ID)
    )
    assert not assigned.is_fallback
    with pytest.raises(InsumapError) as caught:
        use_case(world, ai).execute(
            ForecastInput(actor=doctor_actor(), patient_id=OTHER_PATIENT_ID)
        )
    assert caught.value.code is ErrorCode.NOT_FOUND
    with pytest.raises(PermissionDeniedError):
        use_case(world, ai).execute(
            ForecastInput(
                actor=doctor_actor(permissions=frozenset()), patient_id=PATIENT_ID
            )
        )


def test_the_forecast_has_no_field_that_could_hold_a_dose() -> None:
    names = {item.name for item in fields(GlucoseForecast)}
    names |= {item.name for item in fields(ForecastPoint)}

    assert not any(
        "dose" in name or "unit" in name or "insulin" in name for name in names
    )
