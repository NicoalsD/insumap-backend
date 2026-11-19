from decimal import Decimal

import pytest

from insumap.domain.reports.disclosure import is_too_small, percentage

THRESHOLD = 5


@pytest.mark.parametrize(
    ("count", "hidden"),
    [(0, False), (1, True), (4, True), (5, False), (40, False)],
)
def test_only_positive_counts_below_the_threshold_are_hidden(
    count: int, hidden: bool
) -> None:
    assert is_too_small(count, THRESHOLD) is hidden


def test_a_percentage_is_rounded_to_two_decimals() -> None:
    assert percentage(1, 3, THRESHOLD) is None
    assert percentage(2, 10, THRESHOLD) == Decimal("20.00")
    assert percentage(1, 6, THRESHOLD) == Decimal("16.67")


def test_a_rate_over_a_small_group_is_not_computed() -> None:
    assert percentage(3, 4, THRESHOLD) is None


def test_an_empty_group_has_no_rate() -> None:
    assert percentage(0, 0, 1) is None
