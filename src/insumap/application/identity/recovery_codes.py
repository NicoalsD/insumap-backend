"""Regeneration of the MFA recovery codes (``POST /auth/mfa/recovery-codes``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, final, override
from uuid import UUID

from insumap.application.commands.base import AuditSubject, Command, CommandHandler
from insumap.application.identity.ports import (
    CodeHasherPort,
    CodePurpose,
    MfaFactorRepositoryPort,
    RecoveryCodeGeneratorPort,
)
from insumap.application.identity.second_factor import SecondFactorVerifier
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.errors import (
    InvalidCredentialsError,
    PermissionDeniedError,
)
from insumap.shared.time import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RecoveryCodesResult:
    """The new recovery codes, shown only once."""

    user_id: UUID
    recovery_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class RegenerateMfaRecoveryCodesCommand(Command[RecoveryCodesResult]):
    """A staff member asks for new recovery codes with a current TOTP."""

    audit_action: ClassVar[str] = "MFA_RECOVERY_CODES_REGENERATED"
    audit_entity_type: ClassVar[str] = "USER"

    code: str

    @override
    def audit_subject(self, result: RecoveryCodesResult) -> AuditSubject:
        return AuditSubject(
            clinic_id=self.actor.clinic_id,
            entity_id=result.user_id,
            changed_fields=("recovery_codes",),
        )


@final
class RegenerateMfaRecoveryCodesCommandHandler(
    CommandHandler[RegenerateMfaRecoveryCodesCommand, RecoveryCodesResult]
):
    """Revokes the previous codes and stores new ones, once a TOTP proves the holder.

    Only a TOTP counts here: a recovery code cannot mint more recovery codes.
    The attempts are rate limited by account, like any other second factor check.
    """

    def __init__(
        self,
        *,
        factors: MfaFactorRepositoryPort,
        verifier: SecondFactorVerifier,
        generator: RecoveryCodeGeneratorPort,
        code_count: int,
        code_hasher: CodeHasherPort,
        rate_limit: RateLimitCheck,
        clock: Clock,
    ) -> None:
        self._factors = factors
        self._verifier = verifier
        self._generator = generator
        self._code_count = code_count
        self._code_hasher = code_hasher
        self._rate_limit = rate_limit
        self._clock = clock

    @override
    def handle(self, command: RegenerateMfaRecoveryCodesCommand) -> RecoveryCodesResult:
        actor = command.actor
        if not actor.requires_mfa:
            raise PermissionDeniedError
        self._rate_limit.ensure(str(actor.user_id))
        factor = self._factors.find_totp(actor.user_id)
        if factor is None or not factor.is_confirmed:
            raise PermissionDeniedError
        if not command.code.isdigit() or not self._verifier.check_totp(
            factor, command.code, confirm=False
        ):
            raise InvalidCredentialsError
        codes = self._generator.generate(self._code_count)
        self._factors.replace_recovery_codes(
            actor.user_id,
            [
                self._code_hasher.hash_for_storage(CodePurpose.RECOVERY, code.value)
                for code in codes
            ],
            now=self._clock.now(),
        )
        return RecoveryCodesResult(
            user_id=actor.user_id,
            recovery_codes=tuple(code.formatted() for code in codes),
        )
