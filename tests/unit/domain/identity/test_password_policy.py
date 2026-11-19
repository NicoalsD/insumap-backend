import pytest

from insumap.domain.identity.errors import PasswordPolicyError
from insumap.domain.identity.password_policy import (
    PasswordPolicy,
    PasswordViolation,
    PersonalData,
    normalize_password,
)
from insumap.shared.errors import ErrorCode
from insumap.shared.field_limits import FieldLimits

POLICY = PasswordPolicy(
    min_length=FieldLimits.PASSWORD_MIN_LENGTH,
    max_length=FieldLimits.PASSWORD_MAX_LENGTH,
    common_passwords=["correcthorsebatterystaple", "Password1234"],
)
NOBODY = PersonalData()
PATIENT = PersonalData(
    email_local_part="paciente.uno",
    full_name="Paciente De Prueba Uno",
    document_number="DOC-DE-PRUEBA-0001",
)


def test_accepts_a_long_passphrase_without_composition_rules() -> None:
    assert POLICY.violations("un viaje largo por el río", NOBODY) == ()


def test_length_bounds_are_inclusive() -> None:
    minimum = "x" * FieldLimits.PASSWORD_MIN_LENGTH
    maximum = "y" * FieldLimits.PASSWORD_MAX_LENGTH

    assert POLICY.violations(minimum, NOBODY) == ()
    assert POLICY.violations(maximum, NOBODY) == ()
    assert POLICY.violations(minimum[:-1], NOBODY) == (PasswordViolation.TOO_SHORT,)
    assert POLICY.violations(maximum + "y", NOBODY) == (PasswordViolation.TOO_LONG,)


def test_length_is_measured_after_nfkc() -> None:
    full_width = (
        "\uff46\uff55\uff4c\uff4c\uff57\uff49\uff44\uff54\uff48\uff11\uff12\uff13"
    )

    assert normalize_password(full_width) == "fullwidth123"
    assert POLICY.violations(full_width, NOBODY) == ()


def test_common_passwords_are_compared_case_insensitively() -> None:
    assert POLICY.violations("PASSWORD1234", NOBODY) == (PasswordViolation.TOO_COMMON,)


@pytest.mark.parametrize(
    "candidate",
    ["mi paciente.uno feliz", "soy prueba y nada mas", "doc-de-prueba-0001 x"],
)
def test_rejects_fragments_of_personal_data(candidate: str) -> None:
    assert PasswordViolation.CONTAINS_PERSONAL_DATA in POLICY.violations(
        candidate, PATIENT
    )


def test_short_name_parts_are_not_fragments() -> None:
    personal = PersonalData(full_name="Ana De Uno")

    assert POLICY.violations("ana de uno van lejos", personal) == ()


def test_ensure_acceptable_lists_every_violation_including_reuse() -> None:
    with pytest.raises(PasswordPolicyError) as raised:
        POLICY.ensure_acceptable("Password1234", NOBODY, reused=True)

    error = raised.value
    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.violations == ("PASSWORD_TOO_COMMON", "PASSWORD_REUSED")
    assert error.detail["errors"] == [
        {"field": "body.new_password", "type": "password_policy", "code": code}
        for code in error.violations
    ]


def test_ensure_acceptable_passes_a_good_password() -> None:
    POLICY.ensure_acceptable("un viaje largo por el río", PATIENT)
