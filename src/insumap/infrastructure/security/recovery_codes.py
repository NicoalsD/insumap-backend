"""Random MFA recovery codes."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from typing import final, override

from insumap.application.identity.ports import RecoveryCodeGeneratorPort
from insumap.domain.identity.codes import CROCKFORD_ALPHABET, RecoveryCode
from insumap.shared.field_limits import FieldLimits


@final
class CrockfordRecoveryCodeGenerator(RecoveryCodeGeneratorPort):
    """Codes of ``RECOVERY_CODE_LENGTH`` Crockford characters (50 bits)."""

    @override
    def generate(self, count: int) -> Sequence[RecoveryCode]:
        codes: dict[str, RecoveryCode] = {}
        while len(codes) < count:
            value = "".join(
                secrets.choice(CROCKFORD_ALPHABET)
                for _ in range(FieldLimits.RECOVERY_CODE_LENGTH)
            )
            codes[value] = RecoveryCode(value)
        return list(codes.values())
