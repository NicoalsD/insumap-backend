"""P18 State: the circuit breaker of the AI client moves CLOSED, OPEN and HALF_OPEN."""

from datetime import UTC, datetime, timedelta

import pytest

from insumap.domain.ai.circuit_breaker import (
    CircuitBreaker,
    CircuitPolicy,
    CircuitStatus,
)

START = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
POLICY = CircuitPolicy(failure_threshold=3, open_for=timedelta(seconds=30))


def breaker() -> CircuitBreaker:
    return CircuitBreaker(POLICY)


def fail_n_times(circuit: CircuitBreaker, count: int, at: datetime) -> None:
    for _ in range(count):
        assert circuit.allow(at)
        circuit.record_failure(at)


def test_a_new_circuit_is_closed_and_lets_calls_through() -> None:
    circuit = breaker()

    assert circuit.status is CircuitStatus.CLOSED
    assert circuit.allow(START)


def test_failures_below_the_threshold_keep_it_closed() -> None:
    circuit = breaker()

    fail_n_times(circuit, POLICY.failure_threshold - 1, START)

    assert circuit.status is CircuitStatus.CLOSED
    assert circuit.allow(START)


def test_a_success_resets_the_count_of_consecutive_failures() -> None:
    circuit = breaker()
    fail_n_times(circuit, POLICY.failure_threshold - 1, START)
    circuit.record_success(START)

    fail_n_times(circuit, POLICY.failure_threshold - 1, START)

    assert circuit.status is CircuitStatus.CLOSED


def test_the_threshold_opens_it_and_calls_are_refused() -> None:
    circuit = breaker()

    fail_n_times(circuit, POLICY.failure_threshold, START)

    assert circuit.status is CircuitStatus.OPEN
    assert not circuit.allow(START + timedelta(seconds=29))


def test_after_the_open_period_one_probe_is_admitted() -> None:
    circuit = breaker()
    fail_n_times(circuit, POLICY.failure_threshold, START)
    later = START + POLICY.open_for

    assert circuit.allow(later)
    assert circuit.status is CircuitStatus.HALF_OPEN
    assert not circuit.allow(later)  # the other callers wait for the probe


def test_a_successful_probe_closes_the_circuit() -> None:
    circuit = breaker()
    fail_n_times(circuit, POLICY.failure_threshold, START)
    later = START + POLICY.open_for
    assert circuit.allow(later)

    circuit.record_success(later)

    assert circuit.status is CircuitStatus.CLOSED
    assert circuit.allow(later)


def test_a_failed_probe_opens_it_again_for_a_full_period() -> None:
    circuit = breaker()
    fail_n_times(circuit, POLICY.failure_threshold, START)
    probe_at = START + POLICY.open_for
    assert circuit.allow(probe_at)

    circuit.record_failure(probe_at)

    assert circuit.status is CircuitStatus.OPEN
    assert not circuit.allow(probe_at + timedelta(seconds=1))
    assert circuit.allow(probe_at + POLICY.open_for)


def test_an_open_circuit_ignores_a_stray_report() -> None:
    circuit = breaker()
    fail_n_times(circuit, POLICY.failure_threshold, START)

    circuit.record_success(START)

    assert circuit.status is CircuitStatus.OPEN


@pytest.mark.parametrize(
    ("failure_threshold", "open_seconds"), [(0, 30), (3, 0), (3, -1)]
)
def test_an_invalid_policy_is_refused(
    failure_threshold: int, open_seconds: int
) -> None:
    with pytest.raises(ValueError):
        CircuitPolicy(
            failure_threshold=failure_threshold,
            open_for=timedelta(seconds=open_seconds),
        )
