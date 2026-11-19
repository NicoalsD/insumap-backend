"""Random activation codes (80 bits, Crockford base32)."""

from __future__ import annotations

import secrets
from typing import final, override

from insumap.application.users.ports import ActivationCodeGeneratorPort
from insumap.domain.identity.codes import CROCKFORD_ALPHABET, ActivationCode
from insumap.shared.field_limits import FieldLimits


@final
class CrockfordActivationCodeGenerator(ActivationCodeGeneratorPort):
    """``ACTIVATION_CODE_LENGTH`` characters drawn from the Crockford alphabet."""

    @override
    def generate(self) -> ActivationCode:
        value = "".join(
            secrets.choice(CROCKFORD_ALPHABET)
            for _ in range(FieldLimits.ACTIVATION_CODE_LENGTH)
        )
        return ActivationCode(value)
