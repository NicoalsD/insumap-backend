"""In-memory doubles of the identity ports, shared by unit and API tests."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from insumap.application.common.ids import IdGenerator
from insumap.application.common.unit_of_work import (
    TransactionContext,
    UnitOfWork,
    UnitOfWorkPort,
)
from insumap.application.identity.ports import (
    AccessClaims,
    AccessGrant,
    ActivationProfile,
    ActivationRepositoryPort,
    AuthChallengeRepositoryPort,
    CodeHasherPort,
    CodePurpose,
    ConsentRepositoryPort,
    EncryptedSecret,
    IssuedAccessToken,
    IssuedOpaqueToken,
    KeyedHash,
    LoginIdentity,
    MfaFactorRepositoryPort,
    OpaqueTokenPort,
    PasswordHasherPort,
    PasswordHistoryPort,
    PermissionRepositoryPort,
    PrivacyNotice,
    RecoveryCodeGeneratorPort,
    RefreshLookup,
    RefreshTokenRepositoryPort,
    SecretCipherPort,
    TokenIssuerPort,
    TotpFactor,
    TotpPort,
    UserRepositoryPort,
)
from insumap.application.security.events import (
    SecurityEvent,
    SecurityEventPort,
)
from insumap.application.security.rate_limit import (
    RateLimitDecision,
    RateLimiterPort,
    RateLimitRule,
)
from insumap.domain.common.events import DomainEvent
from insumap.domain.identity.auth_challenge import AuthChallenge
from insumap.domain.identity.codes import RecoveryCode
from insumap.domain.identity.consent import ConsentRecord
from insumap.domain.identity.errors import UnauthenticatedError
from insumap.domain.identity.invitation import CredentialInvitation
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.refresh_token import RefreshToken, RevocationReason
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import UserAccount

VALID_TOTP = "123456"
HASH_PREFIX = "hashed:"
STALE_PREFIX = "stale:"


class FakeUnitOfWork(UnitOfWork):
    def __init__(self, owner: FakeUnitOfWorkPort) -> None:
        self._owner = owner
        self._pending: list[DomainEvent] = []

    def apply_context(self, context: TransactionContext) -> None:
        self._owner.contexts.append(context)

    def collect(self, events: Sequence[DomainEvent]) -> None:
        self._pending.extend(events)

    def commit(self) -> None:
        self._owner.commits += 1
        self._owner.published.extend(self._pending)
        self._pending = []


class FakeUnitOfWorkPort(UnitOfWorkPort):
    def __init__(self) -> None:
        self.contexts: list[TransactionContext] = []
        self.commits = 0
        self.published: list[DomainEvent] = []

    @contextmanager
    def begin(self, context: TransactionContext) -> Iterator[UnitOfWork]:
        self.contexts.append(context)
        yield FakeUnitOfWork(self)


class FakeIds(IdGenerator):
    def __init__(self) -> None:
        self._next = 1000

    def new_id(self) -> UUID:
        self._next += 1
        return UUID(int=self._next)


class FakeUsers(UserRepositoryPort):
    def __init__(self) -> None:
        self.accounts: dict[UUID, UserAccount] = {}

    def add(self, account: UserAccount) -> UserAccount:
        self.accounts[account.user_id] = account
        return account

    def find_login_identity(self, email_normalized: str) -> LoginIdentity | None:
        for account in self.accounts.values():
            if account.email_normalized == email_normalized:
                return LoginIdentity(
                    user_id=account.user_id,
                    status=account.status,
                    password_hash=account.password_hash,
                    token_version=account.token_version,
                    role=account.role if account.membership_active else None,
                    clinic_id=account.clinic_id,
                    clinic_active=not account.clinic_suspended,
                )
        return None

    def get(self, user_id: UUID) -> UserAccount | None:
        return self.accounts.get(user_id)

    def email_taken(self, email_normalized: str, *, except_user_id: UUID) -> bool:
        return any(
            a.email_normalized == email_normalized and a.user_id != except_user_id
            for a in self.accounts.values()
        )

    def save(self, account: UserAccount) -> None:
        self.accounts[account.user_id] = account


class FakePermissions(PermissionRepositoryPort):
    def __init__(self) -> None:
        self.by_role: dict[Role, frozenset[PermissionCode]] = {
            Role.PATIENT: frozenset({PermissionCode.PATIENTS_READ_OWN}),
            Role.DOCTOR: frozenset({PermissionCode.PATIENTS_READ_ASSIGNED}),
        }

    def permissions_for_role(self, role: Role) -> frozenset[PermissionCode]:
        return self.by_role.get(role, frozenset())


class FakeHasher(PasswordHasherPort):
    def __init__(self) -> None:
        self.verifications = 0

    def hash(self, plain: str) -> str:
        return f"{HASH_PREFIX}{plain}"

    def verify(self, password_hash: str, plain: str) -> bool:
        self.verifications += 1
        return password_hash.split(":", 1)[1] == plain

    def needs_rehash(self, password_hash: str) -> bool:
        return password_hash.startswith(STALE_PREFIX)


class FakeHistory(PasswordHistoryPort):
    def __init__(self) -> None:
        self.hashes: dict[UUID, list[str]] = {}

    def recent_hashes(self, user_id: UUID, *, limit: int) -> Sequence[str]:
        return list(reversed(self.hashes.get(user_id, [])))[:limit]

    def add(self, user_id: UUID, password_hash: str, *, now: datetime) -> None:
        self.hashes.setdefault(user_id, []).append(password_hash)


class FakeTokens(TokenIssuerPort):
    """Access tokens are ``access-N`` keys of a table of grants."""

    def __init__(self, lifetime: timedelta = timedelta(minutes=15)) -> None:
        self.grants: dict[str, AccessGrant] = {}
        self._lifetime = lifetime
        self.now = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)

    def issue(self, grant: AccessGrant) -> IssuedAccessToken:
        token = f"access-{len(self.grants) + 1}"
        self.grants[token] = grant
        return IssuedAccessToken(token=token, expires_at=self.now + self._lifetime)

    def decode(self, token: str) -> AccessClaims:
        grant = self.grants.get(token)
        if grant is None:
            raise UnauthenticatedError
        return AccessClaims(
            user_id=grant.user_id,
            role=grant.role,
            clinic_id=grant.clinic_id,
            token_version=grant.token_version,
            session_id=grant.session_id,
            amr=grant.amr,
            token_id=token,
        )


class FakeOpaque(OpaqueTokenPort):
    def __init__(self) -> None:
        self._count = 0

    def new_token(self) -> IssuedOpaqueToken:
        self._count += 1
        plain = f"opaque-{self._count}"
        return IssuedOpaqueToken(plain=plain, token_hash=self.hash(plain))

    def hash(self, plain: str) -> str:
        return f"sha-{plain}"


class FakeRefreshTokens(RefreshTokenRepositoryPort):
    def __init__(self, users: FakeUsers) -> None:
        self.tokens: dict[UUID, RefreshToken] = {}
        self._users = users

    def add(self, token: RefreshToken) -> None:
        self.tokens[token.token_id] = token

    def lookup(self, token_hash: str) -> RefreshLookup | None:
        for token in self.tokens.values():
            if token.token_hash == token_hash:
                account = self._users.accounts.get(token.user_id)
                return RefreshLookup(
                    token_id=token.token_id,
                    user_id=token.user_id,
                    clinic_id=token.clinic_id,
                    role=None if account is None else account.role,
                )
        return None

    def claim(self, token_id: UUID, *, now: datetime) -> RefreshToken | None:
        token = self.tokens.get(token_id)
        if token is None or token.is_revoked:
            return None
        self.tokens[token_id] = token.revoked(reason=RevocationReason.ROTATED, now=now)
        return token

    def get(self, token_id: UUID) -> RefreshToken | None:
        return self.tokens.get(token_id)

    def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        return next(
            (t for t in self.tokens.values() if t.token_hash == token_hash), None
        )

    def link_replacement(self, token_id: UUID, replaced_by_id: UUID) -> None:
        self.tokens[token_id] = replace(
            self.tokens[token_id], replaced_by_id=replaced_by_id
        )

    def revoke_family(
        self, family_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        for key, token in list(self.tokens.items()):
            if token.family_id == family_id:
                self.tokens[key] = token.revoked(reason=reason, now=now)

    def revoke_all_for_user(
        self, user_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        for key, token in list(self.tokens.items()):
            if token.user_id == user_id:
                self.tokens[key] = token.revoked(reason=reason, now=now)


class FakeChallenges(AuthChallengeRepositoryPort):
    def __init__(self) -> None:
        self.challenges: dict[UUID, AuthChallenge] = {}

    def add(self, challenge: AuthChallenge) -> None:
        self.challenges[challenge.challenge_id] = challenge

    def find_by_hash(self, token_hash: str) -> AuthChallenge | None:
        return next(
            (c for c in self.challenges.values() if c.token_hash == token_hash), None
        )

    def save(self, challenge: AuthChallenge) -> None:
        self.challenges[challenge.challenge_id] = challenge


class FakeTotp(TotpPort):
    STEP = 55_555

    def __init__(self) -> None:
        self._count = 0

    def new_secret(self) -> str:
        self._count += 1
        return f"SECRET{self._count}"

    def provisioning_uri(self, secret: str, account_name: str) -> str:
        return f"otpauth://totp/Insumap:{account_name}?secret={secret}"

    def verify(
        self, secret: str, code: str, *, now: datetime, last_used_step: int | None
    ) -> int | None:
        if code != VALID_TOTP:
            return None
        if last_used_step is not None and last_used_step >= self.STEP:
            return None
        return self.STEP


class FakeCipher(SecretCipherPort):
    def encrypt(self, plain: str, *, associated_data: str) -> EncryptedSecret:
        return EncryptedSecret(
            ciphertext=f"{associated_data}#{plain}".encode(), key_id="key-1"
        )

    def decrypt(self, secret: EncryptedSecret, *, associated_data: str) -> str:
        bound, _, plain = secret.ciphertext.decode().partition("#")
        if bound != associated_data:
            raise ValueError("binding changed")
        return plain


class FakeCodeHasher(CodeHasherPort):
    def hash_for_storage(self, purpose: CodePurpose, code: str) -> KeyedHash:
        return KeyedHash(value=f"hmac-{purpose.value}-{code}", key_id="key-1")

    def hashes_for_lookup(self, purpose: CodePurpose, code: str) -> Sequence[str]:
        return [f"hmac-{purpose.value}-{code}"]


class FakeRecoveryCodes(RecoveryCodeGeneratorPort):
    def generate(self, count: int) -> Sequence[RecoveryCode]:
        return [RecoveryCode(f"{index + 1:010d}") for index in range(count)]


class FakeFactors(MfaFactorRepositoryPort):
    def __init__(self) -> None:
        self.totp: dict[UUID, TotpFactor] = {}
        self.revoked: list[UUID] = []
        self.recovery: dict[UUID, list[str]] = {}
        self.used: set[str] = set()

    def find_totp(self, user_id: UUID) -> TotpFactor | None:
        return next(
            (
                f
                for f in self.totp.values()
                if f.user_id == user_id and f.factor_id not in self.revoked
            ),
            None,
        )

    def add_totp(self, factor: TotpFactor, *, now: datetime) -> None:
        self.totp[factor.factor_id] = factor

    def revoke_totp(self, factor_id: UUID, *, now: datetime) -> None:
        self.revoked.append(factor_id)

    def accept_step(
        self, factor_id: UUID, step: int, *, now: datetime, confirm: bool
    ) -> bool:
        factor = self.totp[factor_id]
        if factor.last_used_step is not None and factor.last_used_step >= step:
            return False
        self.totp[factor_id] = replace(
            factor,
            last_used_step=step,
            confirmed_at=now if confirm else factor.confirmed_at,
        )
        return True

    def replace_recovery_codes(
        self, user_id: UUID, codes: Sequence[KeyedHash], *, now: datetime
    ) -> None:
        self.recovery[user_id] = [code.value for code in codes]

    def consume_recovery_code(
        self, user_id: UUID, code_hashes: Sequence[str], *, now: datetime
    ) -> bool:
        for value in code_hashes:
            if value in self.recovery.get(user_id, []) and value not in self.used:
                self.used.add(value)
                return True
        return False


class FakeActivations(ActivationRepositoryPort):
    def __init__(self) -> None:
        self.by_hash: dict[str, CredentialInvitation] = {}
        self.invitations: dict[UUID, CredentialInvitation] = {}
        self.profiles: dict[UUID, ActivationProfile] = {}
        self.clinic_names: dict[UUID, str] = {}

    def add(self, code_hash: str, invitation: CredentialInvitation) -> None:
        self.by_hash[code_hash] = invitation
        self.invitations[invitation.invitation_id] = invitation

    def find_invitation(
        self, code_hashes: Sequence[str]
    ) -> CredentialInvitation | None:
        for value in code_hashes:
            found = self.by_hash.get(value)
            if found is not None:
                current = self.invitations[found.invitation_id]
                return replace(current, patient_id=None)
        return None

    def get_invitation(self, invitation_id: UUID) -> CredentialInvitation | None:
        return self.invitations.get(invitation_id)

    def save_invitation(self, invitation: CredentialInvitation) -> None:
        self.invitations[invitation.invitation_id] = invitation

    def activation_profile(self, patient_id: UUID) -> ActivationProfile | None:
        return self.profiles.get(patient_id)

    def clinic_name(self, clinic_id: UUID) -> str | None:
        return self.clinic_names.get(clinic_id)


class FakeConsents(ConsentRepositoryPort):
    def __init__(self) -> None:
        self.notices: dict[UUID, PrivacyNotice] = {}
        self.records: list[ConsentRecord] = []

    def current_notice(self, clinic_id: UUID) -> PrivacyNotice | None:
        return self.notices.get(clinic_id)

    def add(self, records: Sequence[ConsentRecord]) -> None:
        self.records.extend(records)

    def has_accepted_current(self, patient_id: UUID, clinic_id: UUID) -> bool:
        notice = self.notices.get(clinic_id)
        return notice is not None and any(
            r.patient_id == patient_id
            and r.privacy_notice_version_id == notice.version_id
            for r in self.records
        )


class FakeSecurityEvents(SecurityEventPort):
    def __init__(self) -> None:
        self.events: list[SecurityEvent] = []

    def record(self, event: SecurityEvent) -> None:
        self.events.append(event)


class FakeRateLimiter(RateLimiterPort):
    def __init__(self) -> None:
        self.blocked = False
        self.hits: list[tuple[str, str]] = []

    def hit(self, rule: RateLimitRule, subject: str) -> RateLimitDecision:
        self.hits.append((rule.family, subject))
        return RateLimitDecision(
            allowed=not self.blocked, retry_after_seconds=30 if self.blocked else 0
        )
