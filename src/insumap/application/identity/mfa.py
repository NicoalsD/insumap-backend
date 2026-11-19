"""Second factor of the staff: login challenge and TOTP enrollment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, final

from insumap.application.common.actor import Actor
from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.challenges import ChallengeService
from insumap.application.identity.ports import (
    CodeHasherPort,
    CodePurpose,
    MfaFactorRepositoryPort,
    RecoveryCodeGeneratorPort,
    SecretCipherPort,
    TotpFactor,
    TotpPort,
    UserRepositoryPort,
)
from insumap.application.identity.second_factor import (
    SecondFactorOutcome,
    SecondFactorVerifier,
    totp_secret_binding,
)
from insumap.application.identity.session import AuthenticationResult, SessionIssuer
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
    SecurityEventType,
)
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.auth_challenge import ChallengePurpose
from insumap.domain.identity.errors import (
    AccountNotActiveError,
    ClinicSuspendedError,
    InvalidCredentialsError,
    InvalidStateTransitionError,
    PermissionDeniedError,
    SessionRevokedError,
    UnauthenticatedError,
)
from insumap.domain.identity.user import UserAccount
from insumap.shared.time import Clock

MFA_MACHINE: Final = "mfa_factor"
CONFIRMED: Final = "CONFIRMED"
NOT_ENROLLED: Final = "NOT_ENROLLED"


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifyMfaChallengeInput:
    """The login challenge and the code typed by the user."""

    challenge_token: str
    code: str
    client_ip: str


@final
class VerifyMfaChallengeUseCase:
    """Completes a staff login with a TOTP or a recovery code.

    A wrong code counts an attempt on the challenge and that count is
    committed before answering, so it survives the error.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        challenges: ChallengeService,
        users: UserRepositoryPort,
        verifier: SecondFactorVerifier,
        sessions: SessionIssuer,
        events: SecurityEventPort,
        rate_limit: RateLimitCheck,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._challenges = challenges
        self._users = users
        self._verifier = verifier
        self._sessions = sessions
        self._events = events
        self._rate_limit = rate_limit
        self._clock = clock

    def execute(self, input: VerifyMfaChallengeInput) -> AuthenticationResult:
        """Return a full session or raise the generic credentials error."""
        self._rate_limit.ensure(input.client_ip)
        now = self._clock.now()
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            challenge = self._challenges.find_usable(
                input.challenge_token, purpose=ChallengePurpose.MFA
            )
            if challenge is None:
                raise UnauthenticatedError
            uow.apply_context(
                TransactionContext(
                    user_id=challenge.user_id, clinic_id=challenge.clinic_id
                )
            )
            account = self._users.get(challenge.user_id)
            if account is None:
                raise UnauthenticatedError
            outcome = self._verifier.verify(account.user_id, input.code)
            if outcome is SecondFactorOutcome.REJECTED:
                self._challenges.save(challenge.with_failed_attempt())
                self._record(SecurityEventType.MFA_FAILED, account)
                uow.commit()
                raise InvalidCredentialsError
            if outcome is SecondFactorOutcome.RECOVERY_CODE:
                self._record(SecurityEventType.MFA_RECOVERY_CODE_USED, account)
            self._challenges.save(challenge.consumed(now=now))
            _ensure_can_sign_in(account)
            result = self._sessions.open_full_session(account)
            uow.commit()
        return result

    def _record(self, event_type: SecurityEventType, account: UserAccount) -> None:
        self._events.record(
            SecurityEvent(
                event_type=event_type,
                user_id=account.user_id,
                clinic_id=account.clinic_id,
            )
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class StartMfaEnrollmentInput:
    """The staff member with an enrollment session."""

    actor: Actor


@dataclass(frozen=True, slots=True, kw_only=True)
class StartMfaEnrollmentResult:
    """The TOTP secret and its URI, shown only once."""

    secret: str
    otpauth_uri: str


@final
class StartMfaEnrollmentUseCase:
    """Creates an unconfirmed TOTP factor; its secret is stored encrypted.

    Starting again replaces an abandoned enrollment. An account that already
    has a confirmed factor cannot enroll a second one.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        users: UserRepositoryPort,
        factors: MfaFactorRepositoryPort,
        totp: TotpPort,
        cipher: SecretCipherPort,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._users = users
        self._factors = factors
        self._totp = totp
        self._cipher = cipher
        self._ids = ids
        self._clock = clock

    def execute(self, input: StartMfaEnrollmentInput) -> StartMfaEnrollmentResult:
        """Return the new secret and its ``otpauth://`` URI."""
        actor = input.actor
        if not actor.requires_mfa:
            raise PermissionDeniedError
        now = self._clock.now()
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            account = self._users.get(actor.user_id)
            if account is None or account.email_normalized is None:
                raise SessionRevokedError
            current = self._factors.find_totp(actor.user_id)
            if current is not None and current.is_confirmed:
                raise InvalidStateTransitionError(MFA_MACHINE, CONFIRMED, "enroll")
            if current is not None:
                self._factors.revoke_totp(current.factor_id, now=now)
            secret = self._totp.new_secret()
            factor_id = self._ids.new_id()
            self._factors.add_totp(
                TotpFactor(
                    factor_id=factor_id,
                    user_id=actor.user_id,
                    secret=self._cipher.encrypt(
                        secret,
                        associated_data=totp_secret_binding(factor_id, actor.user_id),
                    ),
                    last_used_step=None,
                    confirmed_at=None,
                ),
                now=now,
            )
            uri = self._totp.provisioning_uri(secret, account.email_normalized)
            uow.commit()
        return StartMfaEnrollmentResult(secret=secret, otpauth_uri=uri)


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmMfaEnrollmentInput:
    """The staff member and the first TOTP of the new factor."""

    actor: Actor
    code: str
    client_ip: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmMfaEnrollmentResult:
    """The full session and the recovery codes, shown only once."""

    authentication: AuthenticationResult
    recovery_codes: tuple[str, ...]


@final
class ConfirmMfaEnrollmentUseCase:
    """Activates the factor with a valid TOTP and opens the full session."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        users: UserRepositoryPort,
        factors: MfaFactorRepositoryPort,
        verifier: SecondFactorVerifier,
        recovery_codes: RecoveryCodeGeneratorPort,
        recovery_code_count: int,
        code_hasher: CodeHasherPort,
        sessions: SessionIssuer,
        rate_limit: RateLimitCheck,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._users = users
        self._factors = factors
        self._verifier = verifier
        self._clock = clock
        self._recovery_codes = recovery_codes
        self._recovery_code_count = recovery_code_count
        self._code_hasher = code_hasher
        self._sessions = sessions
        self._rate_limit = rate_limit

    def execute(self, input: ConfirmMfaEnrollmentInput) -> ConfirmMfaEnrollmentResult:
        """Return the full session and ten new recovery codes."""
        self._rate_limit.ensure(input.client_ip)
        actor = input.actor
        if not actor.requires_mfa:
            raise PermissionDeniedError
        with self._uow.begin(TransactionContext.for_actor(actor)) as uow:
            factor = self._factors.find_totp(actor.user_id)
            if factor is None or factor.is_confirmed:
                status = NOT_ENROLLED if factor is None else CONFIRMED
                raise InvalidStateTransitionError(MFA_MACHINE, status, "confirm")
            if not self._verifier.check_totp(factor, input.code, confirm=True):
                raise InvalidCredentialsError
            account = self._users.get(actor.user_id)
            if account is None:
                raise SessionRevokedError
            _ensure_can_sign_in(account)
            codes = self._recovery_codes.generate(self._recovery_code_count)
            self._factors.replace_recovery_codes(
                actor.user_id,
                [
                    self._code_hasher.hash_for_storage(CodePurpose.RECOVERY, code.value)
                    for code in codes
                ],
                now=self._clock.now(),
            )
            authentication = self._sessions.open_full_session(account)
            uow.commit()
        return ConfirmMfaEnrollmentResult(
            authentication=authentication,
            recovery_codes=tuple(code.formatted() for code in codes),
        )


def _ensure_can_sign_in(account: UserAccount) -> None:
    if not account.can_sign_in:
        raise AccountNotActiveError
    if account.clinic_suspended:
        raise ClinicSuspendedError
