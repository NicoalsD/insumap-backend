import pytest

from insumap.shared.errors import ErrorCode, InsumapError


def test_codes_are_english_upper_snake_case_equal_to_their_names() -> None:
    for code in ErrorCode:
        assert code.value == code.name
        assert code.value.replace("_", "").isalpha()
        assert code.value.isupper()


@pytest.mark.parametrize(
    ("code", "key"),
    [
        (ErrorCode.NOT_FOUND, "not.found"),
        (ErrorCode.PAYLOAD_TOO_LARGE, "payload.too_large"),
        (ErrorCode.CONFLICT, "conflict"),
        (ErrorCode.INTERNAL_ERROR, "internal.error"),
    ],
)
def test_default_message_key_follows_the_domain_convention(
    code: ErrorCode, key: str
) -> None:
    assert code.default_message_key == key


def test_error_uses_the_default_message_key_of_its_code() -> None:
    error = InsumapError(ErrorCode.CONFLICT)

    assert error.code is ErrorCode.CONFLICT
    assert error.message_key == "conflict"
    assert error.params == {}
    assert error.detail == {}


def test_error_keeps_its_own_key_params_and_detail() -> None:
    error = InsumapError(
        ErrorCode.VALIDATION_ERROR,
        message_key="glucose.out_of_range",
        params={"value": 612},
        detail={"field": "value_mg_dl"},
    )

    assert error.message_key == "glucose.out_of_range"
    assert error.params == {"value": 612}
    assert error.detail == {"field": "value_mg_dl"}


def test_params_and_detail_are_read_only_copies() -> None:
    params = {"value": 612}
    error = InsumapError(ErrorCode.CONFLICT, params=params)
    params["value"] = 0

    assert error.params == {"value": 612}
    with pytest.raises(TypeError):
        error.detail["leak"] = "x"  # type: ignore[index]


def test_string_form_is_the_message_key_without_params() -> None:
    error = InsumapError(
        ErrorCode.CONFLICT,
        message_key="patient.duplicated",
        params={"email": "ana@example.test"},
    )

    assert str(error) == "patient.duplicated"
