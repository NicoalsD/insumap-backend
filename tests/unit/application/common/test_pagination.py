from uuid import UUID

import pytest

from insumap.application.common.pagination import (
    build_page,
    decode_cursor,
    encode_cursor,
)
from insumap.shared.errors import ErrorCode, InsumapError


def key(number: int) -> UUID:
    return UUID(int=number)


def test_a_cursor_round_trips_and_is_url_safe() -> None:
    cursor = encode_cursor(key(123456789))

    assert decode_cursor(cursor) == key(123456789)
    assert all(c.isalnum() or c in "-_" for c in cursor)


def test_no_cursor_means_the_first_page() -> None:
    assert decode_cursor(None) is None


@pytest.mark.parametrize("cursor", ["", "***", "abc", "a" * 40])
def test_an_invalid_cursor_is_a_validation_error_on_the_query(cursor: str) -> None:
    with pytest.raises(InsumapError) as error:
        decode_cursor(cursor)

    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert error.value.detail["errors"] == [
        {"field": "query.cursor", "type": "invalid_cursor"}
    ]


def test_a_full_page_points_at_the_next_one() -> None:
    page = build_page([key(1), key(2), key(3)], limit=2, key=lambda k: k)

    assert list(page.items) == [key(1), key(2)]
    assert page.next_cursor is not None
    assert decode_cursor(page.next_cursor) == key(2)


def test_the_last_page_has_no_cursor() -> None:
    page = build_page([key(1), key(2)], limit=2, key=lambda k: k)

    assert list(page.items) == [key(1), key(2)]
    assert page.next_cursor is None


def test_an_empty_listing_is_an_empty_page() -> None:
    page = build_page(list[UUID](), limit=2, key=lambda k: k)

    assert list(page.items) == []
    assert page.next_cursor is None
