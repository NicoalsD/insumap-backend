import pytest

from insumap.domain.identity.codes import (
    CROCKFORD_ALPHABET,
    ActivationCode,
    RecoveryCode,
    format_in_groups,
    normalize_crockford,
)
from insumap.shared.field_limits import FieldLimits

VALID_ACTIVATION = "ABCD-EFGH-JKMN-PQRS"


def test_alphabet_leaves_out_ambiguous_letters() -> None:
    assert len(CROCKFORD_ALPHABET) == 32
    assert not set("ILOU") & set(CROCKFORD_ALPHABET)


@pytest.mark.parametrize(
    "raw",
    [
        VALID_ACTIVATION,
        "abcd-efgh-jkmn-pqrs",
        " ABCD EFGH JKMN PQRS ",
        "ABCDEFGHJKMNPQRS",
    ],
)
def test_activation_code_is_normalized_from_any_typing(raw: str) -> None:
    code = ActivationCode.parse(raw)

    assert code is not None
    assert code.value == "ABCDEFGHJKMNPQRS"
    assert code.formatted() == VALID_ACTIVATION


def test_confusable_letters_are_read_as_digits() -> None:
    code = ActivationCode.parse("OOOO-IIII-LLLL-oil0")

    assert code is not None
    assert code.value == "0000111111110110"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "ABCD-EFGH-JKMN",
        "ABCD-EFGH-JKMN-PQRSX",
        "UUUU-EFGH-JKMN-PQRS",
        "ABCD_EFGH_JKMN_PQRS",
    ],
)
def test_malformed_activation_codes_are_rejected(raw: str) -> None:
    assert ActivationCode.parse(raw) is None


def test_recovery_code_round_trip() -> None:
    code = RecoveryCode.parse("abcde-fghjk")

    assert code is not None
    assert code.value == "ABCDEFGHJK"
    assert code.formatted() == "ABCDE-FGHJK"
    assert RecoveryCode.parse("123456") is None


def test_normalize_respects_the_requested_length() -> None:
    assert normalize_crockford("12345", length=5) == "12345"
    assert (
        normalize_crockford("12345", length=FieldLimits.ACTIVATION_CODE_LENGTH) is None
    )


def test_format_in_groups_splits_by_group_size() -> None:
    assert format_in_groups("ABCDEFGH", group_size=4) == "ABCD-EFGH"
