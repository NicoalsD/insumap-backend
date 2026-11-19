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


def test_request_id_pattern_accepts_an_uppercase_uuid() -> None:
    assert re.fullmatch(FieldLimits.REQUEST_ID_PATTERN, str(uuid.uuid4()).upper())


def test_request_id_maximum_length_is_a_uuid() -> None:
    assert len(str(uuid.uuid4())) == FieldLimits.REQUEST_ID_MAX_LENGTH


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * (FieldLimits.REQUEST_ID_MAX_LENGTH + 1),
        "abc def",
        "front-42.a_b",
        "0123456789abcdef0123456789abcdef",
        "abc\n",
        "<script>",
        "id;drop",
        "ñandú",
    ],
)
def test_request_id_pattern_rejects_unsafe_values(value: str) -> None:
    assert re.fullmatch(FieldLimits.REQUEST_ID_PATTERN, value) is None


def test_activation_code_splits_into_whole_groups() -> None:
    assert (
        FieldLimits.ACTIVATION_CODE_LENGTH % FieldLimits.ACTIVATION_CODE_GROUP_SIZE == 0
    )
    assert FieldLimits.RECOVERY_CODE_LENGTH % FieldLimits.RECOVERY_CODE_GROUP_SIZE == 0


def test_raw_code_inputs_fit_their_formatted_codes() -> None:
    formatted_activation = FieldLimits.ACTIVATION_CODE_LENGTH + (
        FieldLimits.ACTIVATION_CODE_LENGTH // FieldLimits.ACTIVATION_CODE_GROUP_SIZE
    )
    formatted_recovery = FieldLimits.RECOVERY_CODE_LENGTH + (
        FieldLimits.RECOVERY_CODE_LENGTH // FieldLimits.RECOVERY_CODE_GROUP_SIZE
    )

    assert formatted_activation <= FieldLimits.ACTIVATION_CODE_INPUT_MAX_LENGTH
    assert formatted_recovery <= FieldLimits.MFA_CODE_INPUT_MAX_LENGTH
    assert FieldLimits.MFA_CODE_INPUT_MAX_LENGTH >= FieldLimits.TOTP_CODE_LENGTH
