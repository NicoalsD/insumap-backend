import re
import uuid

import pytest

from insumap.shared.field_limits import FieldLimits


def test_every_limit_is_a_positive_integer() -> None:
    limits = {
        name: value
        for name, value in vars(FieldLimits).items()
        if name.isupper() and not name.endswith("_PATTERN")
    }

    assert limits
    assert all(isinstance(value, int) and value > 0 for value in limits.values())


def test_password_bounds_are_ordered() -> None:
    assert FieldLimits.PASSWORD_MIN_LENGTH < FieldLimits.PASSWORD_MAX_LENGTH


def test_default_page_size_fits_the_maximum() -> None:
    assert FieldLimits.PAGE_SIZE_DEFAULT <= FieldLimits.PAGE_SIZE_MAX


def test_request_id_pattern_accepts_a_uuid4() -> None:
    assert re.fullmatch(FieldLimits.REQUEST_ID_PATTERN, str(uuid.uuid4()))


def test_request_id_pattern_accepts_the_maximum_length() -> None:
    value = "a" * FieldLimits.REQUEST_ID_MAX_LENGTH

    assert re.fullmatch(FieldLimits.REQUEST_ID_PATTERN, value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * (FieldLimits.REQUEST_ID_MAX_LENGTH + 1),
        "abc def",
        "abc\n",
        "<script>",
        "id;drop",
        "ñandú",
    ],
)
def test_request_id_pattern_rejects_unsafe_values(value: str) -> None:
    assert re.fullmatch(FieldLimits.REQUEST_ID_PATTERN, value) is None
