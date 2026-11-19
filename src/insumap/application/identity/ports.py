"""Ports of the identity use cases. Infrastructure implements them.

Ports speak in domain types: they never take or return ORM rows, wire
dictionaries or Pydantic models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from insumap.domain.identity.account_state import AccountStatus, PatientAccountState
from insumap.domain.identity.auth_challenge import AuthChallenge
from insumap.domain.identity.codes import RecoveryCode
from insumap.domain.identity.consent import ConsentRecord
from insumap.domain.identity.invitation import CredentialInvitation
from insumap.domain.identity.permissions import PermissionCode
from insumap.domain.identity.refresh_token import RefreshToken, RevocationReason
from insumap.domain.identity.roles import Role
from insumap.domain.identity.user import UserAccount

# Accounts and permissions.


@dataclass(frozen=True, slots=True, kw_only=True)
class LoginIdentity:
    """The minimum the login reads before any context exists.

    It mirrors ``iam.lookup_login_identity``: no name, no clinic name and no
    ``requires_mfa``. The full ``UserAccount`` is read after the provisional
    context is set. ``role`` is ``None`` when the membership is not active.
    """

    user_id: UUID
    status: AccountStatus
    password_hash: str | None
    token_version: int
    role: Role | None
    clinic_id: UUID | None
    clinic_active: bool

    @property
    def can_sign_in(self) -> bool:
        """``True`` if the account is active and has an active membership."""
        return (
            self.role is not None
            and PatientAccountState.from_status(self.status).can_sign_in
        )


class UserRepositoryPort(ABC):
    """Accounts with their membership, role and clinic."""

    @abstractmethod
    def find_login_identity(self, email_normalized: str) -> LoginIdentity | None:
        """Login lookup; it runs before the clinic is known."""

    @abstractmethod
    def get(self, user_id: UUID) -> UserAccount | None:
        """Read an account by primary key, inside its own context."""

    @abstractmethod
    def email_taken(self, email_normalized: str, *, except_user_id: UUID) -> bool:
        """``True`` if another account already uses the email."""

    @abstractmethod
    def save(self, account: UserAccount) -> None:
        """Persist status, email, password hash and token version."""


class PermissionRepositoryPort(ABC):
    """The role to permission matrix of the database."""

    @abstractmethod
    def permissions_for_role(self, role: Role) -> frozenset[PermissionCode]:
        """Return the permissions granted to ``role`` (unknown codes dropped)."""


# Passwords.


class PasswordHasherPort(ABC):
    """Argon2id hashing of passwords (NFKC normalized first)."""

    @abstractmethod
    def hash(self, plain: str) -> str:
        """Return the PHC string of ``plain``."""

    @abstractmethod
    def verify(self, password_hash: str, plain: str) -> bool:
        """``True`` if ``plain`` matches; a malformed hash is ``False``."""

    @abstractmethod
    def needs_rehash(self, password_hash: str) -> bool:
        """``True`` if the hash was made with other parameters."""


class PasswordHistoryPort(ABC):
    """Hashes of the last passwords of an account."""

    @abstractmethod
    def recent_hashes(self, user_id: UUID, *, limit: int) -> Sequence[str]:
        """Return up to ``limit`` hashes, newest first."""

    @abstractmethod
    def add(self, user_id: UUID, password_hash: str, *, now: datetime) -> None:
        """Remember a password hash that is now in use."""


# Tokens.


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessGrant:
    """What an access token asserts about its holder."""

    user_id: UUID
    role: Role
    clinic_id: UUID | None
    token_version: int
    session_id: UUID | None
    amr: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessClaims:
    """Claims of a validated access token."""

    user_id: UUID
    role: Role
    clinic_id: UUID | None
    token_version: int
    session_id: UUID | None
    amr: tuple[str, ...]
    token_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class IssuedAccessToken:
    """A signed access token and the instant it expires."""

    token: str
    expires_at: datetime


class TokenIssuerPort(ABC):
    """Signs and validates access tokens (JWT)."""

    @abstractmethod
    def issue(self, grant: AccessGrant) -> IssuedAccessToken:
        """Sign an access token for ``grant``."""

    @abstractmethod
    def decode(self, token: str) -> AccessClaims:
        """Validate ``token``; any failure raises ``UnauthenticatedError``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class IssuedOpaqueToken:
    """A random opaque token: the plain value is shown once, the hash is kept."""

    plain: str
    token_hash: str


class OpaqueTokenPort(ABC):
    """Random 256-bit tokens stored only as SHA-256."""

    @abstractmethod
    def new_token(self) -> IssuedOpaqueToken:
        """Return a new token and its hash."""

    @abstractmethod
    def hash(self, plain: str) -> str:
        """Return the stored form of ``plain``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshLookup:
    """Owner of a refresh token, found before any context exists.

    It mirrors ``iam.lookup_refresh_token``: just enough to set the
    provisional context. The token row itself is read inside that context.
    """

    token_id: UUID
    user_id: UUID
    clinic_id: UUID | None
    role: Role | None


class RefreshTokenRepositoryPort(ABC):
    """Refresh token families."""

    @abstractmethod
    def add(self, token: RefreshToken) -> None:
        """Store a new token."""

    @abstractmethod
    def lookup(self, token_hash: str) -> RefreshLookup | None:
        """Find the owner of a token by hash, before the context is known."""

    @abstractmethod
    def claim(self, token_id: UUID, *, now: datetime) -> RefreshToken | None:
        """Atomically mark an unrevoked token as ``ROTATED``.

        Returns the token as it was before the claim, or ``None`` if it was
        already revoked (a concurrent claim lost the race, or a replay).
        """

    @abstractmethod
    def get(self, token_id: UUID) -> RefreshToken | None:
        """Read a token by id, inside its owner's context."""

    @abstractmethod
    def find_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Read a token by hash, inside its owner's context."""

    @abstractmethod
    def link_replacement(self, token_id: UUID, replaced_by_id: UUID) -> None:
        """Record which token replaced a rotated one."""

    @abstractmethod
    def revoke_family(
        self, family_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        """Revoke every unrevoked token of a family."""

    @abstractmethod
    def revoke_all_for_user(
        self, user_id: UUID, *, reason: RevocationReason, now: datetime
    ) -> None:
        """Revoke every unrevoked token of an account."""


class AuthChallengeRepositoryPort(ABC):
    """MFA challenges and activation sessions."""

    @abstractmethod
    def add(self, challenge: AuthChallenge) -> None:
        """Store a new challenge."""

    @abstractmethod
    def find_by_hash(self, token_hash: str) -> AuthChallenge | None:
        """Lookup by token hash, before the clinic is known."""

    @abstractmethod
    def save(self, challenge: AuthChallenge) -> None:
        """Persist attempts and consumption."""


# Second factor.


class TotpPort(ABC):
    """RFC 6238 one-time passwords; the time step comes from the ``Clock``."""

    @abstractmethod
    def new_secret(self) -> str:
        """Return a new base32 secret of 160 bits."""

    @abstractmethod
    def provisioning_uri(self, secret: str, account_name: str) -> str:
        """Return the ``otpauth://`` URI the browser turns into a QR code."""

    @abstractmethod
    def verify(
        self, secret: str, code: str, *, now: datetime, last_used_step: int | None
    ) -> int | None:
        """Return the accepted time step, or ``None`` (wrong or replayed)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class EncryptedSecret:
    """Ciphertext of a secret and the fingerprint of the key that sealed it."""

    ciphertext: bytes
    key_id: str


class SecretCipherPort(ABC):
    """Authenticated encryption of secrets the system must read back."""

    @abstractmethod
    def encrypt(self, plain: str, *, associated_data: str) -> EncryptedSecret:
        """Encrypt ``plain`` bound to ``associated_data``."""

    @abstractmethod
    def decrypt(self, secret: EncryptedSecret, *, associated_data: str) -> str:
        """Decrypt; fails if the ciphertext or its binding changed."""


class CodePurpose(StrEnum):
    """Key separation of the keyed code hashes."""

    ACTIVATION = "ACTIVATION"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyedHash:
    """HMAC of a code and the fingerprint of the key used."""

    value: str
    key_id: str


class CodeHasherPort(ABC):
    """Keyed HMAC of human typed codes (activation and recovery)."""

    @abstractmethod
    def hash_for_storage(self, purpose: CodePurpose, code: str) -> KeyedHash:
        """Hash with the current key."""

    @abstractmethod
    def hashes_for_lookup(self, purpose: CodePurpose, code: str) -> Sequence[str]:
        """Hash with every configured key (current first) to find a code."""


class RecoveryCodeGeneratorPort(ABC):
    """Generates random recovery codes."""

    @abstractmethod
    def generate(self, count: int) -> Sequence[RecoveryCode]:
        """Return ``count`` distinct random codes."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TotpFactor:
    """The TOTP factor of an account; unconfirmed while enrolling."""

    factor_id: UUID
    user_id: UUID
    secret: EncryptedSecret
    last_used_step: int | None
    confirmed_at: datetime | None

    @property
    def is_confirmed(self) -> bool:
        """``True`` once a valid code confirmed the enrollment."""
        return self.confirmed_at is not None


class MfaFactorRepositoryPort(ABC):
    """TOTP factors and recovery codes (``iam.mfa_factors``)."""

    @abstractmethod
    def find_totp(self, user_id: UUID) -> TotpFactor | None:
        """The unrevoked TOTP factor of the account, confirmed or not."""

    @abstractmethod
    def add_totp(self, factor: TotpFactor, *, now: datetime) -> None:
        """Store a new unconfirmed factor."""

    @abstractmethod
    def revoke_totp(self, factor_id: UUID, *, now: datetime) -> None:
        """Invalidate a factor (an abandoned enrollment)."""

    @abstractmethod
    def accept_step(
        self, factor_id: UUID, step: int, *, now: datetime, confirm: bool
    ) -> bool:
        """Atomically record ``step`` if it is newer than the last one used.

        With ``confirm`` the factor also becomes active. Returns ``False`` if a
        concurrent verification already used that step.
        """

    @abstractmethod
    def replace_recovery_codes(
        self, user_id: UUID, codes: Sequence[KeyedHash], *, now: datetime
    ) -> None:
        """Revoke the previous recovery codes and store new ones."""

    @abstractmethod
    def consume_recovery_code(
        self, user_id: UUID, code_hashes: Sequence[str], *, now: datetime
    ) -> bool:
        """Atomically mark an unused code as used; ``False`` if none matched."""


# Activation and consent.


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivationProfile:
    """What the activation needs of the imported patient. Never sent back."""

    patient_id: UUID
    clinic_name: str
    birth_date: date
    full_name: str
    contact_email: str | None


class ActivationRepositoryPort(ABC):
    """Invitations and the imported data the activation checks."""

    @abstractmethod
    def find_invitation(
        self, code_hashes: Sequence[str]
    ) -> CredentialInvitation | None:
        """Lookup by keyed code hash, before the clinic is known.

        The result has only what ``iam.lookup_invitation_by_code_hash`` returns:
        ``patient_id``, ``verified_at`` and ``used_at`` are empty until the
        invitation is read again with ``get_invitation`` inside its context.
        """

    @abstractmethod
    def get_invitation(self, invitation_id: UUID) -> CredentialInvitation | None:
        """Read an invitation by primary key."""

    @abstractmethod
    def save_invitation(self, invitation: CredentialInvitation) -> None:
        """Persist status, attempts and timestamps."""

    @abstractmethod
    def activation_profile(self, patient_id: UUID) -> ActivationProfile | None:
        """Birth date, name, contact email and clinic name of the patient."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PrivacyNotice:
    """The current privacy notice version of a clinic."""

    version_id: UUID
    clinic_id: UUID


class ConsentRepositoryPort(ABC):
    """Privacy notices and the append-only consent history."""

    @abstractmethod
    def current_notice(self, clinic_id: UUID) -> PrivacyNotice | None:
        """The notice version in force in the clinic."""

    @abstractmethod
    def add(self, records: Sequence[ConsentRecord]) -> None:
        """Append consent acts."""

    @abstractmethod
    def has_accepted_current(self, patient_id: UUID, clinic_id: UUID) -> bool:
        """``True`` if the latest act on the current notice is an acceptance."""
