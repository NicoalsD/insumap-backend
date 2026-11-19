import pytest

from insumap.domain.ai.subject_ref import SubjectRef


def test_a_pseudonym_with_the_contract_shape_is_accepted() -> None:
    assert SubjectRef("sub_" + "a" * 32).value.startswith("sub_")


@pytest.mark.parametrize(
    "value",
    ["", "sub_" + "A" * 32, "sub_" + "a" * 31, "usr_" + "a" * 32, "sub_" + "g" * 32],
)
def test_anything_else_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="subject ref"):
        SubjectRef(value)
