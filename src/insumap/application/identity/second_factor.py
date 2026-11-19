"""Checks a second factor code: a TOTP or a single-use recovery code."""

from __future__ import annotations

from enum import StrEnum
from typing import Final, final
from uuid import UUID

from insumap.application.identity.ports import (
    CodeHasherPort,
    CodePurpose,
    MfaFactorRepositoryPort,
    SecretCipherPort,
    TotpFactor,
    TotpPort,
)
from insumap.domain.identity.codes import RecoveryCode
from insumap.shared.time import Clock

TOTP_SECRET_AAD_PREFIX: Final = "iam.mfa_factors.secret"  # noqa: S105 - AAD label
AAD_SEPARATOR: Final = "|"


def totp_secret_binding(factor_id: UUID, user_id: UUID) -> str:
    """Associated data that binds a TOTP ciphertext to its row."""
    return AAD_SEPARATOR.join((TOTP_SECRET_AAD_PREFIX, str(factor_id), str(user_id)))


class SecondFactorOutcome(StrEnum):
    """Which factor matched, if any."""

    TOTP = "TOTP"
    RECOVERY_CODE = "RECOVERY_CODE"
    REJECTED = "REJECTED"


@final
class SecondFactorVerifier:
    """Verifies codes against the confirmed factor of an account.

    A TOTP step is accepted once (``last_used_step``), and a recovery code is
    consumed with an atomic update, so a code is never accepted twice.
    """

    def __init__(
        self,
        *,
        factors: MfaFactorRepositoryPort,
        totp: TotpPort,
        cipher: SecretCipherPort,
        code_hasher: CodeHasherPort,
        clock: Clock,
    ) -> None:
        self._factors = factors
        self._totp = totp
        self._cipher = cipher
        self._code_hasher = code_hasher
        self._clock = clock

    def check_totp(self, factor: TotpFactor, code: str, *, confirm: bool) -> bool:
        """Accept a TOTP of ``factor``; with ``confirm`` it also activates it."""
        now = self._clock.now()
        secret = self._cipher.decrypt(
            factor.secret,
            associated_data=totp_secret_binding(factor.factor_id, factor.user_id),
        )
        step = self._totp.verify(
            secret, code, now=now, last_used_step=factor.last_used_step
        )
        return step is not None and self._factors.accept_step(
            factor.factor_id, step, now=now, confirm=confirm
        )

    def verify(self, user_id: UUID, code: str) -> SecondFactorOutcome:
        """Check ``code`` as a TOTP of the confirmed factor or a recovery code."""
        factor = self._factors.find_totp(user_id)
        if factor is None or not factor.is_confirmed:
            return SecondFactorOutcome.REJECTED
        if code.isdigit():
            return (
                SecondFactorOutcome.TOTP
                if self.check_totp(factor, code, confirm=False)
                else SecondFactorOutcome.REJECTED
            )
        recovery = RecoveryCode.parse(code)
        if recovery is not None and self._factors.consume_recovery_code(
            user_id,
            self._code_hasher.hashes_for_lookup(CodePurpose.RECOVERY, recovery.value),
            now=self._clock.now(),
        ):
            return SecondFactorOutcome.RECOVERY_CODE
        return SecondFactorOutcome.REJECTED
