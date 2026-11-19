"""The handlers of the chain: blocking checks first, flags after."""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import final, override

from insumap.domain.monitoring.errors import (
    GlucoseOutOfRangeError,
    ReadingInFutureError,
    ReadingTooOldError,
)
from insumap.domain.monitoring.glucose import IssueCode
from insumap.domain.monitoring.validation.params import ReadingCandidate
from insumap.shared.units import SECONDS_PER_MINUTE


class GlucoseReadingValidationHandler(ABC):
    """Handler of the chain: raise to block, return an issue to flag.

    The order is a business rule. Blocking handlers (range, timestamp) come
    first and raise a ``422`` error, so nothing is saved; the flags (duplicate,
    rate of change, unit) accumulate and the reading is saved ``FLAGGED``. The
    handlers never know the next one: ``set_next`` links them in the container.

    Pattern: P12 Chain of Responsibility
    """

    def __init__(self) -> None:
        self._next: GlucoseReadingValidationHandler | None = None

    @final
    def set_next(
        self, handler: GlucoseReadingValidationHandler
    ) -> GlucoseReadingValidationHandler:
        """Link ``handler`` after this one and return it, to chain calls."""
        self._next = handler
        return handler

    @final
    def validate(
        self, reading: ReadingCandidate, issues: tuple[IssueCode, ...] = ()
    ) -> tuple[IssueCode, ...]:
        """Run this handler, then the rest; return every issue found."""
        flag = self.check(reading)
        found = issues if flag is None else (*issues, flag)
        return found if self._next is None else self._next.validate(reading, found)

    @abstractmethod
    def check(self, reading: ReadingCandidate) -> IssueCode | None:
        """Raise to block, return an issue code to flag, or ``None`` to pass."""


@final
class RangeCheckHandler(GlucoseReadingValidationHandler):
    """Blocks a value outside the measurable range of the clinic."""

    @override
    def check(self, reading: ReadingCandidate) -> IssueCode | None:
        params = reading.params
        if not params.min_mg_dl <= reading.value_mg_dl <= params.max_mg_dl:
            raise GlucoseOutOfRangeError
        return None


@final
class TimestampCheckHandler(GlucoseReadingValidationHandler):
    """Blocks a timestamp too far in the future or older than the allowed delay."""

    @override
    def check(self, reading: ReadingCandidate) -> IssueCode | None:
        params = reading.params
        if reading.measured_at > reading.now + params.future_tolerance:
            raise ReadingInFutureError
        if reading.now - reading.measured_at > params.max_age:
            raise ReadingTooOldError
        return None


@final
class DuplicateCheckHandler(GlucoseReadingValidationHandler):
    """Flags the same value again inside the duplicate window."""

    @override
    def check(self, reading: ReadingCandidate) -> IssueCode | None:
        previous = reading.previous
        if (
            previous is not None
            and previous.value_mg_dl == reading.value_mg_dl
            and abs(reading.measured_at - previous.measured_at)
            <= reading.params.duplicate_window
        ):
            return IssueCode.DUPLICATE_SUSPECTED
        return None


@final
class RateOfChangeCheckHandler(GlucoseReadingValidationHandler):
    """Flags a change per minute that the body cannot produce."""

    @override
    def check(self, reading: ReadingCandidate) -> IssueCode | None:
        previous = reading.previous
        if previous is None:
            return None
        seconds = (reading.measured_at - previous.measured_at).total_seconds()
        if seconds <= 0:
            return None
        minutes = Decimal(str(seconds)) / SECONDS_PER_MINUTE
        change = abs(reading.value_mg_dl - previous.value_mg_dl)
        if change / minutes > reading.params.max_rate_mg_dl_per_min:
            return IssueCode.IMPLAUSIBLE_RATE_OF_CHANGE
        return None


@final
class UnitConsistencyCheckHandler(GlucoseReadingValidationHandler):
    """Flags a value that is about 18 times the previous one, or a fraction of it.

    That is the shape of a mix up between mg/dL and mmol/L; the ratio comes from
    the clinic settings.
    """

    @override
    def check(self, reading: ReadingCandidate) -> IssueCode | None:
        previous = reading.previous
        if previous is None or previous.value_mg_dl <= 0 or reading.value_mg_dl <= 0:
            return None
        ratio = reading.value_mg_dl / previous.value_mg_dl
        limit = reading.params.unit_mismatch_ratio
        if ratio >= limit or ratio <= 1 / limit:
            return IssueCode.UNIT_MISMATCH_SUSPECTED
        return None


def build_validation_chain() -> GlucoseReadingValidationHandler:
    """Blocking handlers first, then the flags; the one place the order lives."""
    head = RangeCheckHandler()
    (
        head.set_next(TimestampCheckHandler())
        .set_next(DuplicateCheckHandler())
        .set_next(RateOfChangeCheckHandler())
        .set_next(UnitConsistencyCheckHandler())
    )
    return head
