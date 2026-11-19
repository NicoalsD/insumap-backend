"""The adapters behind the identity ports, built from the settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from importlib import resources

from pydantic import SecretStr
from sqlalchemy import Engine, create_engine

from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionalUnitOfWorkPort,
    UnitOfWorkPort,
)
from insumap.application.events.publisher import DomainEventPublisher
from insumap.application.identity.ports import (
    ActivationRepositoryPort,
    AuthChallengeRepositoryPort,
    CodeHasherPort,
    ConsentRepositoryPort,
    MfaFactorRepositoryPort,
    OpaqueTokenPort,
    PasswordHasherPort,
    PasswordHistoryPort,
    PermissionRepositoryPort,
    RecoveryCodeGeneratorPort,
    RefreshTokenRepositoryPort,
    SecretCipherPort,
    TokenIssuerPort,
    TotpPort,
    UserRepositoryPort,
)
from insumap.application.security.events import SecurityEventPort
from insumap.application.security.rate_limit import RateLimiterPort
from insumap.infrastructure.persistence.activation_repositories import (
    ActivationRepository,
    ConsentRepository,
)
from insumap.infrastructure.persistence.mfa_repository import MfaFactorRepository
from insumap.infrastructure.persistence.security_event_repository import (
    SecurityEventRepository,
)
from insumap.infrastructure.persistence.session_repositories import (
    AuthChallengeRepository,
    RefreshTokenRepository,
)
from insumap.infrastructure.persistence.transactions import (
    CurrentSession,
    SqlTransactionFactory,
)
from insumap.infrastructure.persistence.user_repositories import (
    PasswordHistoryRepository,
    PermissionRepository,
    UserRepository,
)
from insumap.infrastructure.security.code_hasher import HmacCodeHasher
from insumap.infrastructure.security.jwt_service import JwtConfig, JwtTokenService
from insumap.infrastructure.security.keys import KeyRing
from insumap.infrastructure.security.opaque_tokens import Sha256OpaqueTokens
from insumap.infrastructure.security.password_hasher import (
    Argon2PasswordHasher,
    PasswordHashingConfig,
)
from insumap.infrastructure.security.rate_limiter import InMemoryRateLimiter
from insumap.infrastructure.security.recovery_codes import (
    CrockfordRecoveryCodeGenerator,
)
from insumap.infrastructure.security.secret_cipher import AesGcmSecretCipher
from insumap.infrastructure.security.totp import PyOtpTotp
from insumap.infrastructure.security.uuid7 import Uuid7Generator
from insumap.shared.config import Settings
from insumap.shared.time import Clock

COMMON_PASSWORDS_FILE = "common_passwords.txt"


def load_common_passwords() -> list[str]:
    """The list of passwords the policy refuses, one per line."""
    text = (
        resources.files("insumap.infrastructure.security")
        .joinpath(COMMON_PASSWORDS_FILE)
        .read_text(encoding="utf-8")
    )
    return [line.strip() for line in text.splitlines() if line.strip()]


def _ring(current: SecretStr, previous: SecretStr | None) -> KeyRing:
    return KeyRing(current=current, previous=previous)


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentityAdapters:
    """Every port the identity use cases need, wired by ``Container``.

    Tests pass their own doubles; production gets ``build_identity_adapters``.
    """

    unit_of_work: UnitOfWorkPort
    users: UserRepositoryPort
    permissions: PermissionRepositoryPort
    password_history: PasswordHistoryPort
    refresh_tokens: RefreshTokenRepositoryPort
    challenges: AuthChallengeRepositoryPort
    mfa_factors: MfaFactorRepositoryPort
    activations: ActivationRepositoryPort
    consents: ConsentRepositoryPort
    security_events: SecurityEventPort
    password_hasher: PasswordHasherPort
    tokens: TokenIssuerPort
    opaque_tokens: OpaqueTokenPort
    totp: TotpPort
    cipher: SecretCipherPort
    code_hasher: CodeHasherPort
    recovery_codes: RecoveryCodeGeneratorPort
    rate_limiter: RateLimiterPort
    ids: IdGenerator


def build_engine(settings: Settings) -> Engine:
    """The engine of ``insumap_app``; it connects on first use."""
    return create_engine(
        settings.database_url.get_secret_value(), pool_pre_ping=True, future=True
    )


def build_identity_adapters(
    settings: Settings,
    *,
    clock: Clock,
    publisher: DomainEventPublisher,
    engine: Engine,
    current: CurrentSession | None = None,
) -> IdentityAdapters:
    """Build the production adapters: PostgreSQL, Argon2id, JWT and TOTP.

    ``current`` is the session holder every repository of the process shares, so
    the repositories of other modules join the same transaction.
    """
    current = current or CurrentSession()
    unit_of_work = TransactionalUnitOfWorkPort(
        SqlTransactionFactory(engine, current), publisher
    )
    jwt_keys = _ring(settings.jwt_secret, settings.jwt_secret_previous)
    mfa_keys = _ring(settings.mfa_encryption_key, settings.mfa_encryption_key_previous)
    code_keys = _ring(settings.code_hmac_key, settings.code_hmac_key_previous)
    return IdentityAdapters(
        unit_of_work=unit_of_work,
        users=UserRepository(current),
        permissions=PermissionRepository(current),
        password_history=PasswordHistoryRepository(current),
        refresh_tokens=RefreshTokenRepository(current),
        challenges=AuthChallengeRepository(current),
        mfa_factors=MfaFactorRepository(current),
        activations=ActivationRepository(current),
        consents=ConsentRepository(current),
        security_events=SecurityEventRepository(current),
        password_hasher=Argon2PasswordHasher(
            PasswordHashingConfig(
                memory_kib=settings.argon2_memory_kib,
                time_cost=settings.argon2_time_cost,
                parallelism=settings.argon2_parallelism,
                max_concurrency=settings.password_hash_max_concurrency,
            )
        ),
        tokens=JwtTokenService(
            keys=jwt_keys,
            config=JwtConfig(
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                access_ttl=timedelta(minutes=settings.jwt_access_minutes),
                leeway=timedelta(seconds=settings.jwt_leeway_seconds),
            ),
            clock=clock,
        ),
        opaque_tokens=Sha256OpaqueTokens(),
        totp=PyOtpTotp(valid_window=settings.mfa_totp_valid_window),
        cipher=AesGcmSecretCipher(mfa_keys),
        code_hasher=HmacCodeHasher(code_keys),
        recovery_codes=CrockfordRecoveryCodeGenerator(),
        rate_limiter=InMemoryRateLimiter(clock),
        ids=Uuid7Generator(clock),
    )
