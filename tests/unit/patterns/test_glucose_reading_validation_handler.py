"""P12 Chain of Responsibility: order, blocking and flags of the reading checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from insumap.domain.monitoring.errors import (
    GlucoseOutOfRangeError,
    ReadingInFutureError,
    ReadingTooOldError,
)
from insumap.domain.monitoring.glucose import IssueCode
from insumap.domain.monitoring.validation import (
    GlucoseReadingValidationHandler,
    PreviousReading,
    ReadingCandidate,
    ValidationParams,
    build_validation_chain,
)

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)

# Parameters declared by the test, like the row of the database would.
PARAMS = ValidationParams(
    min_mg_dl=Decimal(20),
    max_mg_dl=Decimal(600),
    future_tolerance=timedelta(minutes=5),
    max_age=timedelta(hours=72),
    duplicate_window=timedelta(minutes=2),
    max_rate_mg_dl_per_min=Decimal(10),
    unit_mismatch_ratio=Decimal(10),
)


def candidate(
    value: str = "110",
    *,
    at: datetime = NOW,
    previous: PreviousReading | None = None,
) -> ReadingCandidate:
    return ReadingCandidate(
        value_mg_dl=Decimal(value),
        measured_at=at,
        now=NOW,
        params=PARAMS,
        previous=previous,
    )


def previous(value: str, minutes_ago: float) -> PreviousReading:
    return PreviousReading(
        value_mg_dl=Decimal(value), measured_at=NOW - timedelta(minutes=minutes_ago)
    )


@pytest.fixture
def chain() -> GlucoseReadingValidationHandler:
    return build_validation_chain()


def test_a_normal_reading_has_no_issues(chain: GlucoseReadingValidationHandler) -> None:
    assert chain.validate(candidate(previous=previous("100", 30))) == ()


def test_range_is_inclusive_and_blocks_outside(
    chain: GlucoseReadingValidationHandler,
) -> None:
    assert chain.validate(candidate("20")) == ()
    assert chain.validate(candidate("600")) == ()
    with pytest.raises(GlucoseOutOfRangeError):
        chain.validate(candidate("19.9"))
    with pytest.raises(GlucoseOutOfRangeError):
        chain.validate(candidate("600.1"))


def test_the_first_blocking_handler_wins(
    chain: GlucoseReadingValidationHandler,
) -> None:
    future = NOW + timedelta(hours=2)

    with pytest.raises(GlucoseOutOfRangeError):
        chain.validate(candidate("900", at=future))


def test_future_tolerance_and_maximum_age(
    chain: GlucoseReadingValidationHandler,
) -> None:
    assert chain.validate(candidate(at=NOW + timedelta(minutes=5))) == ()
    with pytest.raises(ReadingInFutureError):
        chain.validate(candidate(at=NOW + timedelta(minutes=5, seconds=1)))
    assert chain.validate(candidate(at=NOW - timedelta(hours=72))) == ()
    with pytest.raises(ReadingTooOldError):
        chain.validate(candidate(at=NOW - timedelta(hours=72, seconds=1)))


def test_same_value_inside_the_window_is_flagged_as_duplicate(
    chain: GlucoseReadingValidationHandler,
) -> None:
    flagged = chain.validate(candidate("110", previous=previous("110", 2)))

    assert flagged == (IssueCode.DUPLICATE_SUSPECTED,)
    assert chain.validate(candidate("110", previous=previous("110", 3))) == ()
    assert chain.validate(candidate("111", previous=previous("110", 1))) == ()


def test_rate_of_change_is_flagged_above_the_maximum(
    chain: GlucoseReadingValidationHandler,
) -> None:
    # 100 mg/dL in 5 minutes is 20 per minute; the limit of the test is 10.
    assert chain.validate(candidate("200", previous=previous("100", 5))) == (
        IssueCode.IMPLAUSIBLE_RATE_OF_CHANGE,
    )
    assert chain.validate(candidate("150", previous=previous("100", 5))) == ()


def test_unit_mismatch_is_flagged_in_both_directions(
    chain: GlucoseReadingValidationHandler,
) -> None:
    assert IssueCode.UNIT_MISMATCH_SUSPECTED in chain.validate(
        candidate("300", previous=previous("25", 600))
    )
    assert IssueCode.UNIT_MISMATCH_SUSPECTED in chain.validate(
        candidate("25", previous=previous("300", 600))
    )


def test_flags_accumulate_in_chain_order(
    chain: GlucoseReadingValidationHandler,
) -> None:
    found = chain.validate(candidate("300", previous=previous("25", 1)))

    assert found == (
        IssueCode.IMPLAUSIBLE_RATE_OF_CHANGE,
        IssueCode.UNIT_MISMATCH_SUSPECTED,
    )


def test_a_reading_without_history_only_gets_the_blocking_checks(
    chain: GlucoseReadingValidationHandler,
) -> None:
    assert chain.validate(candidate("500")) == ()


def test_the_thresholds_come_from_the_parameters(
    chain: GlucoseReadingValidationHandler,
) -> None:
    strict = ValidationParams(
        min_mg_dl=Decimal(100),
        max_mg_dl=Decimal(120),
        future_tolerance=timedelta(0),
        max_age=timedelta(hours=1),
        duplicate_window=timedelta(minutes=1),
        max_rate_mg_dl_per_min=Decimal(1),
        unit_mismatch_ratio=Decimal(2),
    )
    reading = ReadingCandidate(
        value_mg_dl=Decimal(150), measured_at=NOW, now=NOW, params=strict
    )

    with pytest.raises(GlucoseOutOfRangeError):
        chain.validate(reading)
