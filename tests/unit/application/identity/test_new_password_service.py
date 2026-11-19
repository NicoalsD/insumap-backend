import pytest

from insumap.domain.identity.errors import PasswordPolicyError
from insumap.domain.identity.password_policy import PersonalData
from tests.support.identity_world import NEW_PASSWORD, PATIENT_USER, IdentityWorld

PERSONAL = PersonalData(email_local_part="paciente", full_name="Persona de Prueba")


def test_accepted_password_is_hashed_and_remembered() -> None:
    world = IdentityWorld()

    password_hash = world.passwords.accepted_hash(PATIENT_USER, NEW_PASSWORD, PERSONAL)
    world.passwords.remember(PATIENT_USER, password_hash)

    assert password_hash == f"hashed:{NEW_PASSWORD}"
    assert world.history.hashes[PATIENT_USER] == [password_hash]


def test_a_password_from_the_history_is_refused() -> None:
    world = IdentityWorld()
    world.passwords.remember(PATIENT_USER, f"hashed:{NEW_PASSWORD}")

    with pytest.raises(PasswordPolicyError) as caught:
        world.passwords.accepted_hash(PATIENT_USER, NEW_PASSWORD, PERSONAL)

    assert "REUSED" in str(caught.value.detail)
