"""Login with email and password (API.md, ``POST /auth/login``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from insumap.application.common.unit_of_work import TransactionContext, UnitOfWorkPort
from insumap.application.identity.challenges import ChallengePolicy, ChallengeService
from insumap.application.identity.ports import (
    LoginIdentity,
    MfaFactorRepositoryPort,
    PasswordHasherPort,
    UserRepositoryPort,
)
from insumap.application.identity.session import AuthenticationResult, SessionIssuer
from insumap.application.security.rate_limit import RateLimitCheck
from insumap.domain.identity.auth_challenge import ChallengePurpose
from insumap.domain.identity.email import EmailAddress
from insumap.domain.identity.errors import (
    AccountNotActiveError,
    ClinicSuspendedError,
    InvalidCredentialsError,
)
from insumap.domain.identity.session import LoginStatus
from insumap.domain.identity.user import UserAccount


@dataclass(frozen=True, slots=True, kw_only=True)
class LoginInput:
    """Credentials as typed, plus the client IP for the rate limit."""

    email: str
    password: str
    client_ip: str


@final
class LoginUseCase:
    """Checks the password and answers one of the three login states.

    Exactly one Argon2id verification runs per attempt: when the email does not
    exist, or the account has no password yet, the decoy hash is verified so
    the timing does not reveal accounts. The reason an account cannot sign in
    is told only after a correct password.
    """

    def __init__(
        self,
        *,
        uow: UnitOfWorkPort,
        users: UserRepositoryPort,
        hasher: PasswordHasherPort,
        decoy_hash: str,
        mfa_factors: MfaFactorRepositoryPort,
        challenges: ChallengeService,
        challenge_policy: ChallengePolicy,
        sessions: SessionIssuer,
        rate_limit: RateLimitCheck,
    ) -> None:
        self._uow = uow
        self._users = users
        self._hasher = hasher
        self._decoy_hash = decoy_hash
        self._mfa_factors = mfa_factors
        self._challenges = challenges
        self._challenge_policy = challenge_policy
        self._sessions = sessions
        self._rate_limit = rate_limit

    def execute(self, input: LoginInput) -> AuthenticationResult:
        """Return the login state, or raise the generic credentials error."""
        self._rate_limit.ensure(input.client_ip)
        email = EmailAddress.from_input(input.email)
        with self._uow.begin(TransactionContext.anonymous()) as uow:
            identity = self._verified(
                self._users.find_login_identity(email.normalized), input.password
            )
            if not identity.can_sign_in:
                raise AccountNotActiveError
            if not identity.clinic_active:
                raise ClinicSuspendedError
            uow.apply_context(
                TransactionContext(
                    user_id=identity.user_id,
                    clinic_id=identity.clinic_id,
                    role=identity.role,
                )
            )
            account = self._users.get(identity.user_id)
            if account is None:
                raise InvalidCredentialsError
            account = self._rehashed(account, input.password)
            result = self._next_step(account)
            uow.commit()
        return result

    def _verified(self, identity: LoginIdentity | None, password: str) -> LoginIdentity:
        stored = identity.password_hash if identity is not None else None
        matched = self._hasher.verify(stored or self._decoy_hash, password)
        if identity is None or stored is None or not matched:
            raise InvalidCredentialsError
        return identity

    def _rehashed(self, account: UserAccount, password: str) -> UserAccount:
        if account.password_hash is None or not self._hasher.needs_rehash(
            account.password_hash
        ):
            return account
        updated = account.with_password_hash(self._hasher.hash(password))
        self._users.save(updated)
        return updated

    def _next_step(self, account: UserAccount) -> AuthenticationResult:
        if not account.requires_mfa:
            return self._sessions.open_full_session(account)
        factor = self._mfa_factors.find_totp(account.user_id)
        if factor is None or not factor.is_confirmed:
            return self._sessions.enrollment_session(account)
        token = self._challenges.issue(
            purpose=ChallengePurpose.MFA,
            policy=self._challenge_policy,
            user_id=account.user_id,
            clinic_id=account.clinic_id,
        )
        return AuthenticationResult(
            status=LoginStatus.MFA_CHALLENGE, challenge_token=token
        )
